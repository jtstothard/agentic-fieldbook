# Live Kanban adapter evidence probe

`scripts/capture_kanban_evidence.py` captures a timestamped JSON artifact from the
live Hermes Kanban board without mutating production state. The live phase uses
only `boards list`, `stats --json`, `diagnostics --json`, `assignees --json`, and
status-filtered `list --json` commands. It follows the returned running-task IDs
with read-only `show <id> --json` calls to capture claim/run evidence.

Lifecycle writes (create, claim, and synthetic failure handling) run through the
experimental adapter under a temporary `HERMES_HOME` and `evidence-shadow`
board. The artifact records the temporary-home and shadow-DB checks and an
explicit `production_mutations_attempted: false` boundary.

## Reproduce

From the repository root, with Hermes configured:

```bash
python3 scripts/capture_kanban_evidence.py --output /tmp/kanban-live-evidence.json
```

Exit status is `0` only when every live read succeeds and the shadow probe
passes. Status `2` means `insufficient`; the artifact still contains all
successful observations and explicit gaps. Other process failures are ordinary
Python/tool failures and must not be interpreted as passing evidence.

The artifact includes the exact repository ref, UTC timestamps, commands,
redacted stdout/stderr, parsed JSON where available, live board identity, and
known limitations. It is local evidence and should be attached or copied to a
review record rather than written into a production board.
