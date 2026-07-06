# PR 14: `anon-proxy-store` CLI — list / show / purge / prune

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** The store is append-only and invisible; false positives permanently
occupy placeholder identities (a real session accumulated 186 PERSON entries,
mostly shell fragments — issue #13). Give users a way to inspect and clean a
persisted store file. Also the user-agency requirement: data a tool holds
about you must be viewable and deletable.

**Architecture:** New module `anon_proxy/store_cli.py`, console script
`anon-proxy-store` in `pyproject.toml`. Operates on the `--store` JSON file
directly (documented requirement: stop the server first, or accept that a
concurrent server overwrites edits — print a warning). Purging removes the
mapping but NEVER decrements counters, so freed indexes are never reused
(a reused `<PERSON_3>` would silently remap old conversation history).

**Commands:**
- `list [--label PERSON] [--min-len N] [--max-len N]` — table of token, label,
  value (truncated), value length.
- `show <token>` — full value for one token.
- `purge <token>...` — remove specific mappings.
- `prune --label X --max-len N [--dry-run]` — bulk-remove junk (the
  issue-#13 cleanup: `prune --label PERSON --max-len 3`).

## Global constraints

- See overview plan. Branch: `feat/store-cli` off `main`.
- Destructive ops (`purge`, `prune`) print what they removed; `prune` supports
  `--dry-run`; both write a `.bak` copy of the store file before modifying
  (never destroy the only copy of a mapping the user may still need to unmask
  old transcripts).

---

### Task 1: Core operations (pure functions)

**Files:**
- Create: `anon_proxy/store_cli.py`
- Test: `tests/test_store_cli.py`

**Interfaces:**
- Produces: `filter_entries(data: dict, label: str | None, min_len: int | None,
  max_len: int | None) -> list[tuple[str, str, str]]` (token, label, value);
  `purge_tokens(data: dict, tokens: list[str]) -> tuple[dict, list[str]]`
  (new data, removed tokens). `data` is the `PIIStore.to_dict()` shape
  (`{"reverse": {...}, "counters": {...}}`).

- [ ] **Step 1: Failing tests**

```python
def _store_data():
    return {"reverse": {"<PERSON_1>": "Alice Smith", "<PERSON_2>": "la",
                        "<EMAIL_1>": "alice@x.com"},
            "counters": {"PERSON": 2, "EMAIL": 1}}

class TestFilterEntries:
    def test_by_label(self):
        rows = filter_entries(_store_data(), "PERSON", None, None)
        assert [r[0] for r in rows] == ["<PERSON_1>", "<PERSON_2>"]

    def test_by_max_len(self):
        rows = filter_entries(_store_data(), None, None, 3)
        assert [r[0] for r in rows] == ["<PERSON_2>"]

class TestPurge:
    def test_purge_removes_mapping_keeps_counter(self):
        data, removed = purge_tokens(_store_data(), ["<PERSON_2>"])
        assert removed == ["<PERSON_2>"]
        assert "<PERSON_2>" not in data["reverse"]
        assert data["counters"]["PERSON"] == 2   # NEVER reuse indexes

    def test_purge_unknown_token_reports_nothing(self):
        data, removed = purge_tokens(_store_data(), ["<PERSON_99>"])
        assert removed == [] and len(data["reverse"]) == 3
```

- [ ] **Step 2: Implement** (pure dict-in/dict-out; use
`anon_proxy.mapping._parse_token` for labels; `filter_entries` sorts by token).

- [ ] **Step 3: Commit** — `"feat: store CLI core operations"`.

### Task 2: argparse entrypoint + safety rails

**Files:**
- Modify: `anon_proxy/store_cli.py` (add `main()`), `pyproject.toml`
  (`[project.scripts] anon-proxy-store = "anon_proxy.store_cli:main"`)
- Test: `tests/test_store_cli.py` (invoke `main()` with argv + tmp files —
  real file I/O, no mocks)

- [ ] **Step 1: Failing tests**

```python
def test_cli_prune_dry_run_changes_nothing(tmp_path, capsys):
    p = tmp_path / "store.json"
    p.write_text(json.dumps(_store_data()))
    main(["prune", "--label", "PERSON", "--max-len", "3",
          "--store", str(p), "--dry-run"])
    assert "would remove <PERSON_2>" in capsys.readouterr().out
    assert json.loads(p.read_text()) == _store_data()

def test_cli_prune_writes_backup_then_modifies(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps(_store_data()))
    main(["prune", "--label", "PERSON", "--max-len", "3", "--store", str(p)])
    assert json.loads((tmp_path / "store.json.bak").read_text()) == _store_data()
    new = json.loads(p.read_text())
    assert "<PERSON_2>" not in new["reverse"]
    assert new["counters"]["PERSON"] == 2

def test_cli_list_and_show(tmp_path, capsys):
    p = tmp_path / "store.json"
    p.write_text(json.dumps(_store_data()))
    main(["show", "<EMAIL_1>", "--store", str(p)])
    assert "alice@x.com" in capsys.readouterr().out
```

- [ ] **Step 2: Implement**

`main(argv: list[str] | None = None) -> int` with subparsers; `--store`
defaults to `os.environ.get("ANON_PROXY_STORE")` (same env var the server
uses — one source of truth). Before any write: `shutil.copyfile(path,
path + ".bak")`, then reuse the atomic `.tmp`+`os.replace` write pattern from
`mapping.py:95-100` (extract it into a shared helper
`anon_proxy.mapping.atomic_write_json(path, data)` and use it from both —
server `_write_store_json` too; delete the duplicate). Every command prints a
one-line warning if it can't rule out a running server (no lock file exists —
just always print "if the proxy is running, restart it to pick up changes").

- [ ] **Step 3: Full suite + collection check (pyproject change), README
  section "Cleaning the store" with the issue-#13 one-liner
  (`anon-proxy-store prune --label PERSON --max-len 3`), commit** —
  `"feat: anon-proxy-store CLI (list/show/purge/prune)"`.
