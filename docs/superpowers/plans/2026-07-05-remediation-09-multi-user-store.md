# PR 09: `--multi-user` — per-client store namespacing

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** On a shared deployment (Kevin's k8s), one global PIIStore lets any
client unmask any other client's values by echoing placeholder tokens. Add an
explicit multi-user mode that namespaces the store (and therefore the caches)
per client identity; keep today's behavior as the single-user default.

**Architecture:** Client identity = SHA-256 (first 16 hex) of the auth
credential (`x-api-key` or `authorization` header). A `MaskerRegistry` holds
one `Masker` per client id, all sharing ONE `PrivacyFilter` (the model is the
expensive part; `Masker(filter=...)` already supports injection) and the same
extra detectors/ignore labels. The mask/content caches must be per-client too —
they map text → masked-with-*this-store's*-tokens, so they live in the Masker
and come along naturally. Persistence: `--store PATH` in multi-user mode treats
PATH as a directory, one `<client_id>.json` per client. Unauthenticated
requests in multi-user mode → 401 (fail closed).

## Global constraints

- See overview plan. Branch: `feat/multi-user-store` off `main`.
- High-risk change class (auth/isolation) → positive AND negative tests
  mandatory: same client shares tokens; different clients must not.

---

### Task 1: MaskerRegistry

**Files:**
- Create: `anon_proxy/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces:
  `client_id(headers: Mapping[str, str]) -> str | None` (None = no credential);
  `MaskerRegistry(make_masker: Callable[[PIIStore], Masker], store_dir: str | None)`
  with `get(cid: str) -> Masker` (lazy create, loads `<store_dir>/<cid>.json`
  if present) and `store_path(cid) -> str | None`.

- [ ] **Step 1: Failing tests**

```python
class TestClientId:
    def test_x_api_key_hashed(self):
        cid = client_id({"x-api-key": "sk-ant-123"})
        assert cid and len(cid) == 16 and "sk-ant" not in cid

    def test_authorization_fallback(self):
        assert client_id({"authorization": "Bearer tok"}) is not None

    def test_no_credential_is_none(self):
        assert client_id({"content-type": "application/json"}) is None

    def test_different_keys_different_ids(self):
        assert client_id({"x-api-key": "a"}) != client_id({"x-api-key": "b"})

class TestMaskerRegistry:
    def test_same_client_same_masker(self, make_filter):
        reg = MaskerRegistry(lambda s: Masker(filter=make_filter(), store=s),
                             store_dir=None)
        assert reg.get("abc") is reg.get("abc")

    def test_clients_are_isolated(self, make_filter, fake_pipeline):
        reg = MaskerRegistry(lambda s: Masker(filter=make_filter(), store=s),
                             store_dir=None)
        m_a, m_b = reg.get("aaaa"), reg.get("bbbb")
        m_a.store.get_or_create("PERSON", "Alice")
        # Client B echoing A's token must NOT unmask it — the oracle test.
        assert m_b.unmask("hi <PERSON_1>") == "hi <PERSON_1>"

    def test_store_dir_roundtrip(self, tmp_path, make_filter):
        reg = MaskerRegistry(lambda s: Masker(filter=make_filter(), store=s),
                             store_dir=str(tmp_path))
        reg.get("cafe").store.get_or_create("PERSON", "Alice")
        reg.get("cafe").store.save(reg.store_path("cafe"))
        reg2 = MaskerRegistry(lambda s: Masker(filter=make_filter(), store=s),
                              store_dir=str(tmp_path))
        assert reg2.get("cafe").store.original("<PERSON_1>") == "Alice"
```

- [ ] **Step 2: Implement `anon_proxy/registry.py`**

```python
"""Per-client Masker namespacing for shared (multi-user) deployments.

Identity is a hash of the client's upstream credential: it requires no extra
configuration, and two clients share a namespace exactly when they'd share an
upstream account anyway. The hash (not the key) is used for filenames/logs so
the store directory never contains credential material.
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Callable, Mapping

from anon_proxy.mapping import PIIStore
from anon_proxy.masker import Masker

_CRED_HEADERS = ("x-api-key", "authorization")


def client_id(headers: Mapping[str, str]) -> str | None:
    lowered = {k.lower(): v for k, v in headers.items()}
    for h in _CRED_HEADERS:
        v = lowered.get(h)
        if v:
            return hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]
    return None


class MaskerRegistry:
    def __init__(self, make_masker: Callable[[PIIStore], Masker],
                 store_dir: str | None) -> None:
        self._make = make_masker
        self._store_dir = store_dir
        self._maskers: dict[str, Masker] = {}
        self._lock = threading.Lock()
        if store_dir:
            os.makedirs(store_dir, exist_ok=True)

    def store_path(self, cid: str) -> str | None:
        return os.path.join(self._store_dir, f"{cid}.json") if self._store_dir else None

    def get(self, cid: str) -> Masker:
        with self._lock:
            masker = self._maskers.get(cid)
            if masker is None:
                store = PIIStore()
                path = self.store_path(cid)
                if path and os.path.exists(path):
                    store = PIIStore.load(path)
                masker = self._make(store)
                self._maskers[cid] = masker
            return masker
```

- [ ] **Step 3: Full suite, commit** — `"feat: MaskerRegistry for per-client store namespacing"`.

### Task 2: Server wiring

**Files:**
- Modify: `anon_proxy/server.py` (`build_app` gains `registry: MaskerRegistry | None = None`;
  `_handle_proxy` resolves the masker per request; `_maybe_save_store` uses the
  per-client path; `main()` gains `--multi-user` flag and builds the registry:
  `make_masker = lambda store: Masker(filter=pf or PrivacyFilter(), store=store,
  extra_detectors=extra_detectors, ignore_labels=cfg.ignore_labels)` — note the
  single shared `pf`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `client_id`, `MaskerRegistry` from Task 1.
- Produces: in multi-user mode — 401 JSON error for credential-less requests;
  per-client masking end-to-end.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.anyio
async def test_multi_user_requires_credential(multi_user_app):
    resp = await post_messages(multi_user_app, headers={})  # no x-api-key
    assert resp.status_code == 401

@pytest.mark.anyio
async def test_multi_user_clients_isolated(multi_user_app, stub_upstream):
    # Client A masks Alice -> <PERSON_1>. Upstream echoes <PERSON_1> to both.
    # A's response unmasks to Alice; B's response keeps the literal token.
    ra = await post_messages(multi_user_app, headers={"x-api-key": "A"},
                             text="I am Alice")
    rb = await post_messages(multi_user_app, headers={"x-api-key": "B"},
                             text="hello")
    assert "Alice" in body_text(ra)
    assert "<PERSON_1>" in body_text(rb) or "Alice" not in body_text(rb)
```

(Build `multi_user_app` on the existing stub-upstream fixture; `stub_upstream`
returns a canned response containing `<PERSON_1>`.)

- [ ] **Step 2: Implement**

In `_handle_proxy`, where `masker` is read from app state:

```python
    registry: MaskerRegistry | None = request.app.state.registry
    if registry is not None:
        cid = client_id(request.headers)
        if cid is None:
            return Response(
                content=json.dumps({"error": "multi-user mode requires an "
                                    "x-api-key or authorization header"}),
                status_code=401, media_type="application/json")
        masker = registry.get(cid)
        store_save_path = registry.store_path(cid)
    else:
        masker = request.app.state.masker
        store_save_path = request.app.state.store_path
```

Thread `store_save_path` into `_maybe_save_store` (replace its
`app_state.store_path` read with a parameter). In `main()`:
`--multi-user` flag (env `ANON_PROXY_MULTI_USER`); when set, build the
registry and pass `registry=registry` to `build_app`; `--store` is then a
directory. Refuse `--multi-user` without `--host` binding beyond loopback?
No — multi-user on loopback is legitimate (reverse proxy in front); just
document.

- [ ] **Step 3: Full suite, docs, commit**

README: new "Multi-user deployments" section (when to use, the 401 rule,
store directory layout). SECURITY.md: replace the "malicious local user"
paragraph's silence on shared hosts with: single-user mode assumes one trust
domain; multi-user mode isolates unmask access per credential, but the host
operator still sees everything. Commit:
`"feat: --multi-user mode with per-client store namespacing"`.
