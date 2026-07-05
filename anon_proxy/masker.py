import json
import re
import sys
from typing import Callable, Protocol

from anon_proxy.known_entities import KnownEntityDetector
from anon_proxy.mapping import PIIStore
from anon_proxy.privacy_filter import PIIEntity, PrivacyFilter


class Detector(Protocol):
    def detect(self, text: str) -> list[PIIEntity]: ...


class Masker:
    """Composes PrivacyFilter + PIIStore to mask outgoing text and unmask LLM replies.

    One Masker instance per conversation: the store accumulates entities across
    turns so the same PII always gets the same placeholder.

    `extra_detectors` is a list of objects with a `detect(text) -> list[PIIEntity]`
    method whose spans are merged into the primary filter's output. Overlapping
    spans from different detectors are resolved by preferring the longer span.
    """

    def __init__(
        self,
        filter: PrivacyFilter | None = None,
        store: PIIStore | None = None,
        extra_detectors: list[Detector] | None = None,
        canary: str = "warn",
        min_known_entity_len: int = 6,
    ) -> None:
        if canary not in {"warn", "fix", "off"}:
            raise ValueError("canary must be one of: warn, fix, off")
        if min_known_entity_len < 0:
            raise ValueError("min_known_entity_len must be >= 0")
        self._filter = filter or PrivacyFilter()
        self._store = store or PIIStore()
        self._canary = canary
        self._canary_detectors: list[Detector] = list(extra_detectors or [])
        self._pre_detectors: list[Detector] = []
        if min_known_entity_len:
            self._pre_detectors.append(
                KnownEntityDetector(self._store, min_len=min_known_entity_len)
            )
        self._pre_detectors.extend(self._canary_detectors)

    @property
    def store(self) -> PIIStore:
        return self._store

    def mask(self, text: str) -> str:
        ml_entities: list[PIIEntity] = list(self._filter.detect(text))

        entities: list[PIIEntity] = []
        for detector in self._pre_detectors:
            entities.extend(detector.detect(text))
        entities.extend(ml_entities)
        entities = _resolve_overlaps(entities)
        masked = self._substitute(text, entities)

        canary_hits = self._canary_hits(masked)
        if canary_hits:
            for hit in canary_hits:
                suffix = " - masking now" if self._canary == "fix" else ""
                print(
                    f"warning: canary: {hit.label} {hit.text!r} survived masking{suffix}",
                    file=sys.stderr,
                )
            if self._canary == "fix":
                masked = self._substitute(masked, canary_hits)
        return masked

    def unmask(self, text: str) -> str:
        return self._sub(text, lambda s: s)

    def unmask_json(self, text: str) -> str:
        """Unmask tokens sitting inside a JSON string context.

        Replacements are JSON-escaped so an original containing `"`, `\\`, or
        control chars doesn't break the surrounding JSON. Use this for raw
        JSON fragments like Anthropic's `input_json_delta.partial_json` where
        the unmasked text flows through an unparsed string.
        """
        return self._sub(text, lambda s: json.dumps(s)[1:-1])

    def _sub(self, text: str, transform: Callable[[str], str]) -> str:
        tokens = self._store.tokens()
        if not tokens:
            return text
        # Longest-first so "<PERSON_1>" can't shadow "<PERSON_10>".
        pattern = re.compile(
            "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
        )

        def repl(m: re.Match[str]) -> str:
            original = self._store.original(m.group(0))
            return transform(original) if original is not None else m.group(0)

        return pattern.sub(repl, text)

    def _substitute(self, text: str, entities: list[PIIEntity]) -> str:
        # Replace right-to-left so earlier spans' offsets stay valid.
        for e in sorted(entities, key=lambda x: x.start, reverse=True):
            token = self._store.get_or_create(e.label, e.text).token
            text = text[: e.start] + token + text[e.end :]
        return text

    def _canary_hits(self, masked: str) -> list[PIIEntity]:
        if self._canary == "off" or not self._canary_detectors:
            return []
        hits: list[PIIEntity] = []
        for detector in self._canary_detectors:
            hits.extend(detector.detect(masked))
        return _drop_placeholder_overlaps(_resolve_overlaps(hits), masked)


def _resolve_overlaps(entities: list[PIIEntity]) -> list[PIIEntity]:
    """Keep a non-overlapping subset of spans.

    Greedy: sort by (start, -length, -score) so earlier and longer spans land first.
    Walk left-to-right; when a span overlaps the last kept, replace only if the
    new one is strictly longer (ties: higher score wins). Touching spans at
    `prev.end == next.start` do not overlap.
    """
    if not entities:
        return entities
    ordered = sorted(
        entities,
        key=lambda e: (e.start, -(e.end - e.start), -e.score, e.label),
    )
    kept: list[PIIEntity] = []
    for e in ordered:
        if kept and e.start < kept[-1].end:
            prev = kept[-1]
            prev_len = prev.end - prev.start
            cur_len = e.end - e.start
            if cur_len > prev_len or (cur_len == prev_len and e.score > prev.score):
                kept[-1] = e
            continue
        kept.append(e)
    return kept


def _drop_placeholder_overlaps(entities: list[PIIEntity], text: str) -> list[PIIEntity]:
    if not entities:
        return entities
    placeholders = [
        match.span() for match in re.finditer(r"<[A-Z][A-Z0-9_]*_\d+>", text)
    ]
    if not placeholders:
        return entities
    return [
        entity
        for entity in entities
        if not any(
            entity.start < end and start < entity.end for start, end in placeholders
        )
    ]
