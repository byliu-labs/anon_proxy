import json

from anon_proxy.mapping import PIIStore


def test_store_file_roundtrip_preserves_counters(tmp_path):
    store = PIIStore()
    store.get_or_create("PERSON", "Alice Smith")
    store.get_or_create("PERSON", "Bob")
    path = tmp_path / "store.json"

    store.save(str(path))
    restored = PIIStore.load(str(path))

    assert restored.original("<PERSON_1>") == "Alice Smith"
    assert restored.original("<PERSON_2>") == "Bob"
    assert restored.get_or_create("PERSON", "Carol").token == "<PERSON_3>"


def test_store_save_removes_tmp_file(tmp_path):
    store = PIIStore()
    store.get_or_create("EMAIL", "alice@example.com")
    path = tmp_path / "store.json"

    store.save(str(path))

    assert not (tmp_path / "store.json.tmp").exists()
    assert json.loads(path.read_text()) == {
        "reverse": {"<EMAIL_1>": "alice@example.com"},
        "counters": {"EMAIL": 1},
    }
