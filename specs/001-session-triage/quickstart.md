# Quickstart: validating the roundup

Prerequisites: Python 3.9+, `git`, `jq`; for the live checks a running Corgi runtime and an agent in a Corgi pane; `gh` signed in (optional); macOS for copy-back.

## 1. Offline test suite (no Corgi, no network, no clipboard)

```bash
make test
```

Runs `python3 -m unittest discover -s tests -t .` against recorded Corgi replies, git fixture repositories built in temporary directories, and stub `corgi`, `gh`, `pbcopy` and `slack-pbcopy` executables that log what they receive. Expected: all tests pass. Covers SC-002, SC-003, SC-004 (mechanical part), SC-006 and SC-007.

## 2. Seeded world categories

```bash
python3 -m unittest tests.test_seeded_world -v
```

The seeded world (`tests/fixtures/world/`) holds at least 12 labelled sessions plus a subagent, an Ask Corgi helper and the caller. Expected: every top-level session exactly once, none of the excluded ones, 100% of labelled mechanical categories correct, using the recorded judgments file.

## 3. Gathering against the live runtime (read-only)

From an agent in a Corgi pane:

```bash
time roundup/scripts/roundup gather > "$TMPDIR/digest.json"
jq '.sessions | length, (map(.agent_state) | group_by(.) | map({(.[0]): length}) | add)' "$TMPDIR/digest.json"
```

Expected: under 30 seconds (SC-001); the count matches the live top-level agent panes minus the caller; `caller.excluded` is true.

## 4. Full review in each harness

```bash
make install          # Claude Code
make install-codex    # Codex
```

Start `/cc-roundup:roundup` (Codex: the `roundup` skill). Expected: categorized overview in under 2 minutes for about 70 sessions; nothing changes before you confirm; declining every step leaves all panes untouched; closed sessions show up in `corgi history` and resume with `corgi resume PROVIDER SESSION`.

## 5. Unreachable runtime

```bash
CORGI_SOCKET=/nonexistent roundup/scripts/roundup gather; echo "exit=$?"
```

Expected: `exit=3` and Corgi's own `connect ENOENT` error on stderr. (Corgi honours `CORGI_SOCKET`; verified during research, R12. The offline suite covers the same path with the stub's unreachable mode.)
