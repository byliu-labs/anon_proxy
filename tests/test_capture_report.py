import json

import pytest

from anon_proxy.capture_report import iter_entities, main, summarize


ENTITIES = [
    {"source": "ml", "label": "PERSON", "score": 0.97, "len": 11},
    {"source": "ml", "label": "PERSON", "score": 0.62, "len": 4},
    {"source": "regex", "label": "SSN", "score": 1.0, "len": 11},
    {"source": "canary", "label": "PHONE", "score": 1.0, "len": 12},
]


def _record(entities):
    return {
        "request": {"pre_mask": {"messages": [{"content": "Alice"}]}},
        "timing_ms": {"detector_calls": [{"op": "mask", "entities": entities}]},
    }


def _write_capture(tmp_path, records):
    path = tmp_path / "capture.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_iter_entities_reads_real_capture_file_and_skips_old_records(tmp_path):
    path = _write_capture(
        tmp_path,
        [_record(ENTITIES[:2]), {"timing_ms": {"detector_calls": [{"op": "mask"}]}}],
    )

    assert list(iter_entities(path)) == ENTITIES[:2]


def test_summarize_reports_score_evidence_and_canary_counts():
    summary = summarize(ENTITIES)

    assert summary["labels"]["PERSON"]["count"] == 2
    assert summary["labels"]["PERSON"]["min_score"] == 0.62
    assert summary["labels"]["PERSON"]["p50_score"] == pytest.approx(0.795)
    assert sum(summary["labels"]["PERSON"]["histogram"].values()) == 2
    assert summary["by_source"] == {"ml": 2, "regex": 1, "canary": 1}
    assert summary["canary_hits"] == 1


def test_cli_never_prints_raw_capture_text(tmp_path, capsys):
    path = _write_capture(tmp_path, [_record(ENTITIES)])

    assert main([str(path)]) == 0

    output = capsys.readouterr().out
    assert "PERSON" in output
    assert "0.62" in output
    assert "canary" in output
    assert "Alice" not in output


def test_cli_missing_file_is_loud(capsys):
    assert main(["/definitely/missing/capture.jsonl"]) == 1
    assert "error" in capsys.readouterr().err
