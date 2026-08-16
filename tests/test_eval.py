import pytest

from anon_proxy.eval import LabeledSpan, aggregate, load_corpus


def test_perfect_predictions_score_one_for_every_label():
    text = "Alice called 555-867-5309."
    gold = [
        LabeledSpan(start=0, end=5, label="PERSON"),
        LabeledSpan(start=13, end=25, label="PHONE"),
    ]

    report = aggregate([{"text": text, "gold": gold, "predicted": gold}])

    assert report["char_leak_rate"] == 0
    assert report["per_label"]["PERSON"]["precision"] == 1
    assert report["per_label"]["PERSON"]["recall"] == 1
    assert report["per_label"]["PERSON"]["f1"] == 1
    assert report["per_label"]["PHONE"]["precision"] == 1
    assert report["per_label"]["PHONE"]["recall"] == 1
    assert report["per_label"]["PHONE"]["f1"] == 1
    assert report["overall"]["exact_f1"] == 1


def test_missed_prediction_reduces_recall_and_counts_leaked_chars():
    text = "Alice called 555-867-5309."
    gold = [
        LabeledSpan(start=0, end=5, label="PERSON"),
        LabeledSpan(start=13, end=25, label="PHONE"),
    ]
    predicted = [LabeledSpan(start=0, end=5, label="PERSON")]

    report = aggregate([{"text": text, "gold": gold, "predicted": predicted}])

    assert report["per_label"]["PHONE"]["precision"] == 0
    assert report["per_label"]["PHONE"]["recall"] == 0
    assert report["leaked_chars"] == 12
    assert report["gold_chars"] == 17
    assert report["char_leak_rate"] == pytest.approx(12 / 17)


def test_over_detection_counts_against_precision_without_leaking_chars():
    text = "No private text."
    predicted = [LabeledSpan(start=0, end=2, label="PERSON")]

    report = aggregate([{"text": text, "gold": [], "predicted": predicted}])

    assert report["per_label"]["PERSON"]["precision"] == 0
    assert report["per_label"]["PERSON"]["recall"] == 0
    assert report["per_label"]["PERSON"]["support"] == 0
    assert report["char_leak_rate"] == 0


def test_wrong_label_is_not_a_span_match_but_still_covers_privacy_chars():
    text = "Alice"
    gold = [LabeledSpan(start=0, end=5, label="PERSON")]
    predicted = [LabeledSpan(start=0, end=5, label="PHONE")]

    report = aggregate([{"text": text, "gold": gold, "predicted": predicted}])

    assert report["per_label"]["PERSON"]["recall"] == 0
    assert report["per_label"]["PHONE"]["precision"] == 0
    assert report["char_leak_rate"] == 0


def test_partial_overlap_is_relaxed_match_but_not_exact_match():
    text = "Alice Smith"
    gold = [LabeledSpan(start=0, end=11, label="PERSON")]
    predicted = [LabeledSpan(start=0, end=5, label="PERSON")]

    report = aggregate([{"text": text, "gold": gold, "predicted": predicted}])

    assert report["per_label"]["PERSON"]["precision"] == 1
    assert report["per_label"]["PERSON"]["recall"] == 1
    assert report["per_label"]["PERSON"]["f1"] == 1
    assert report["per_label"]["PERSON"]["exact_f1"] == 0
    assert report["leaked_chars"] == 6


def test_one_prediction_can_only_match_one_gold_span():
    text = "Alice Bob"
    gold = [
        LabeledSpan(start=0, end=5, label="PERSON"),
        LabeledSpan(start=6, end=9, label="PERSON"),
    ]
    predicted = [LabeledSpan(start=0, end=9, label="PERSON")]

    report = aggregate([{"text": text, "gold": gold, "predicted": predicted}])

    assert report["per_label"]["PERSON"]["precision"] == 1
    assert report["per_label"]["PERSON"]["recall"] == pytest.approx(0.5)
    assert report["per_label"]["PERSON"]["f1"] == pytest.approx(2 / 3)
    assert report["char_leak_rate"] == 0


def test_load_corpus_reads_jsonl_and_normalizes_labels(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        '{"id":"one","text":"Alice","spans":[{"start":0,"end":5,"label":"private_person"}]}\n',
        encoding="utf-8",
    )

    [example] = load_corpus(path)

    assert example.id == "one"
    assert example.text == "Alice"
    assert example.spans == [LabeledSpan(start=0, end=5, label="PERSON")]


def test_load_corpus_rejects_invalid_span_bounds(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        '{"id":"bad","text":"Alice","spans":[{"start":0,"end":99,"label":"PERSON"}]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 1.*span 0"):
        load_corpus(path)


def test_committed_corpus_schema_is_valid():
    examples = load_corpus("tests/data/pii_corpus.jsonl")

    assert len(examples) >= 40
    labels = {span.label for example in examples for span in example.spans}
    assert {
        "PERSON",
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "ORGANIZATION",
        "DATE",
        "SECRET",
        "GOVT_ID",
    }.issubset(labels)
