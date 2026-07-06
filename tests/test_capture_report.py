import json

from anon_proxy.capture_report import build_report, main


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_build_report_aggregates_safe_entity_histograms(tmp_path):
    path = tmp_path / "capture.jsonl"
    _write_jsonl(
        path,
        [
            {
                "request": {"pre_mask": {"messages": [{"content": "Alice"}]}},
                "timing_ms": {
                    "detector_calls": [
                        {
                            "op": "mask",
                            "entities": [
                                {
                                    "label": "PERSON",
                                    "score": 0.94,
                                    "len": 5,
                                    "source": "ml",
                                },
                                {
                                    "label": "EMAIL",
                                    "score": 1.0,
                                    "len": 15,
                                    "source": "regex",
                                },
                            ],
                        }
                    ]
                },
            },
            {
                "timing_ms": {
                    "detector_calls": [
                        {
                            "op": "mask",
                            "entities": [
                                {
                                    "label": "PERSON",
                                    "score": 0.81,
                                    "len": 3,
                                    "source": "ml",
                                }
                            ],
                        }
                    ]
                },
            },
        ],
    )

    report = build_report([path])

    assert report["files"] == [str(path)]
    assert report["labels"]["PERSON"]["count"] == 2
    assert report["labels"]["PERSON"]["score_histogram"]["0.8-0.9"] == 1
    assert report["labels"]["PERSON"]["score_histogram"]["0.9-1.0"] == 1
    assert report["labels"]["PERSON"]["sources"] == {"ml": 2}
    assert report["labels"]["EMAIL"]["sources"] == {"regex": 1}
    assert "Alice" not in json.dumps(report)


def test_cli_prints_histograms_without_raw_capture_text(tmp_path, capsys):
    path = tmp_path / "capture.jsonl"
    _write_jsonl(
        path,
        [
            {
                "request": {"pre_mask": {"messages": [{"content": "Alice"}]}},
                "timing_ms": {
                    "detector_calls": [
                        {
                            "op": "mask",
                            "entities": [
                                {
                                    "label": "PERSON",
                                    "score": 0.94,
                                    "len": 5,
                                    "source": "ml",
                                }
                            ],
                        }
                    ]
                },
            }
        ],
    )

    assert main([str(path)]) == 0

    out = capsys.readouterr().out
    assert "PERSON" in out
    assert "0.9-1.0" in out
    assert "Alice" not in out
