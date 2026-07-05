from __future__ import annotations

import pytest

from anon_proxy.masker import Masker
from anon_proxy.regex_detector import RegexDetector

from .conftest import span


class TestPostMaskCanary:
    def test_warn_mode_logs_and_forwards(self, make_masker, capsys) -> None:
        masker = make_masker(
            extra_detectors=[RegexDetector({"EMAIL": r"[\w.]+@[\w.]+"})],
            canary="warn",
        )
        masker._pre_detectors = []

        out = masker.mask("contact bob@x.com ok")

        assert "bob@x.com" in out
        assert "canary" in capsys.readouterr().err

    def test_fix_mode_masks_the_miss(self, make_masker) -> None:
        masker = make_masker(
            extra_detectors=[RegexDetector({"EMAIL": r"[\w.]+@[\w.]+"})],
            canary="fix",
        )
        masker._pre_detectors = []

        out = masker.mask("contact bob@x.com ok")

        assert "bob@x.com" not in out
        assert "<EMAIL_1>" in out

    def test_off_mode_silent(self, make_masker, capsys) -> None:
        masker = make_masker(
            extra_detectors=[RegexDetector({"EMAIL": r"[\w.]+@[\w.]+"})],
            canary="off",
        )
        masker._pre_detectors = []

        masker.mask("contact bob@x.com ok")

        assert "canary" not in capsys.readouterr().err

    def test_no_false_canary_on_clean_mask(self, make_masker, capsys) -> None:
        masker = make_masker(
            extra_detectors=[RegexDetector({"EMAIL": r"[\w.]+@[\w.]+"})],
            canary="warn",
        )

        masker.mask("contact bob@x.com ok")

        assert "canary" not in capsys.readouterr().err


def test_learned_value_masks_later_in_code_context(make_masker, fake_filter) -> None:
    masker = make_masker()
    prose = "My name is Alice Smith."
    fake_filter.set(prose, [span("private_person", 11, 22, text=prose)])
    assert "<PERSON_1>" in masker.mask(prose)

    code = 'os.environ["OWNER"] = "Alice Smith"'
    fake_filter.set(code, [])

    assert masker.mask(code) == 'os.environ["OWNER"] = "<PERSON_1>"'


@pytest.mark.parametrize("canary", ["loud", "", "WARN"])
def test_canary_rejects_unknown_modes(canary: str, fake_filter, store) -> None:
    with pytest.raises(ValueError, match="canary"):
        Masker(filter=fake_filter, store=store, canary=canary)
