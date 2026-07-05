from __future__ import annotations

from anon_proxy.default_patterns import DEFAULT_PATTERNS
from anon_proxy.server import _effective_patterns


def test_effective_patterns_include_defaults_by_default() -> None:
    assert _effective_patterns(None, True) == DEFAULT_PATTERNS


def test_effective_patterns_let_user_override_default_label() -> None:
    patterns = _effective_patterns({"EMAIL": "custom"}, True)

    assert patterns["EMAIL"] == "custom"


def test_effective_patterns_can_disable_defaults() -> None:
    assert _effective_patterns({"EMAIL": "custom"}, False) == {"EMAIL": "custom"}
