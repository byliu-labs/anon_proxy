# PR 13 Evidence Check — `min_score`

Status: blocked, not implemented in this branch.

The plan requires replaying a real capture with known 186-PERSON pollution before
adding a `min_score` knob. I searched this worktree and the parent checkout for
capture JSON/JSONL artifacts and found none:

```bash
rg --files /Users/boyuliu/pyprojects/projects/anon_proxy -g '*capture*' -g '*.jsonl' -g '*.json' -g '!uv.lock'
find /Users/boyuliu/pyprojects/projects/anon_proxy -maxdepth 4 -type f -name '*capture*'
```

Only `anon_proxy/capture.py` exists. Without the real polluted capture, the score
histogram cannot distinguish junk spans from plausible hits, so this branch does
not ship `min_score`.
