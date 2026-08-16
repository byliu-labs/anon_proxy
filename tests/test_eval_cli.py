import json

from anon_proxy import eval as eval_mod
from anon_proxy.privacy_filter import PIIEntity


class FakeFilter:
    def __init__(self, **_kwargs):
        pass

    def detect(self, text):
        if "Alice" in text:
            return [PIIEntity("PERSON", "Alice", text.index("Alice"), 5, 0.99)]
        return []


def test_cli_emits_json_report_with_detector_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_mod, "PrivacyFilter", FakeFilter)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"id":"one","text":"Alice","spans":[{"start":0,"end":5,"label":"PERSON"}]}\n',
        encoding="utf-8",
    )

    assert eval_mod.main([str(corpus), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["per_label"]["PERSON"]["recall"] == 1
    assert report["char_leak_rate"] == 0


def test_cli_fails_when_recall_floor_is_breached(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_mod, "PrivacyFilter", FakeFilter)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"id":"one","text":"Bob","spans":[{"start":0,"end":3,"label":"PERSON"}]}\n',
        encoding="utf-8",
    )

    assert eval_mod.main([str(corpus), "--fail-under-recall", "PERSON=0.9"]) == 1

    assert "PERSON recall 0.000 below floor 0.900" in capsys.readouterr().err


def test_cli_prints_table_without_raw_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_mod, "PrivacyFilter", FakeFilter)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"id":"one","text":"Alice","spans":[{"start":0,"end":5,"label":"PERSON"}]}\n',
        encoding="utf-8",
    )

    assert eval_mod.main([str(corpus)]) == 0

    output = capsys.readouterr().out
    assert "PERSON" in output
    assert "Alice" not in output
