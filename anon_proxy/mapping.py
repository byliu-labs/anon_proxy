import json
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Placeholder:
    label: str
    index: int
    token: str


class PIIStore:
    """In-memory bidirectional map from (label, canonical value) to placeholder tokens.

    Cross-turn consistency: the same entity (modulo casing / whitespace) always
    maps to the same token for the life of this store. The reverse map preserves
    the first-seen original form so un-masking restores the user's casing.
    """

    def __init__(self) -> None:
        self._forward: dict[tuple[str, str], Placeholder] = {}
        self._reverse: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def get_or_create(self, label: str, value: str) -> Placeholder:
        normalized_label = _placeholder_label(label)
        key = (normalized_label, _canonical(value))
        existing = self._forward.get(key)
        if existing is not None:
            return existing
        index = self._counters.get(normalized_label, 0) + 1
        self._counters[normalized_label] = index
        token = f"<{normalized_label}_{index}>"
        ph = Placeholder(label=normalized_label, index=index, token=token)
        self._forward[key] = ph
        self._reverse[token] = value
        return ph

    def original(self, token: str) -> str | None:
        return self._reverse.get(token)

    def tokens(self) -> list[str]:
        return list(self._reverse.keys())

    def items(self) -> list[tuple[str, str]]:
        return list(self._reverse.items())

    def __len__(self) -> int:
        return len(self._reverse)

    def to_dict(self) -> dict:
        return {
            "reverse": dict(self._reverse),
            "counters": dict(self._counters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PIIStore":
        store = cls()
        store._reverse = dict(data["reverse"])
        store._counters = dict(data["counters"])
        for token, original in store._reverse.items():
            parsed = _parse_token(token)
            if parsed is None:
                continue
            label, index = parsed
            key = (label, _canonical(original))
            store._forward[key] = Placeholder(label=label, index=index, token=token)
        return store

    def save(self, path: str) -> None:
        atomic_write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: str) -> "PIIStore":
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}: invalid JSON: {e}") from e
        return cls.from_dict(data)


_WHITESPACE = re.compile(r"\s+")


def _canonical(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _placeholder_label(label: str) -> str:
    trimmed = label[len("private_") :] if label.startswith("private_") else label
    return trimmed.upper()


_TOKEN_PARSE_RE = re.compile(r"<([A-Z][A-Z0-9_]*)_(\d+)>")


def _parse_token(token: str) -> tuple[str, int] | None:
    match = _TOKEN_PARSE_RE.fullmatch(token)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
