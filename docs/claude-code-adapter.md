# Claude Code executor boundary

`ClaudeCodeAdapter` launches only through a trusted, non-symlink, root-owned,
non-group/world-writable executable inside bubblewrap. Bubblewrap is the
authoritative security boundary and is required; the host's absence of bwrap
therefore fails closed rather than falling back to an unconfined subprocess.
The command uses `--clearenv` and an explicit minimal environment.

Workspace snapshots are supplemental evidence, not enforcement. They record
portable file type, mode, uid/gid, and file digest metadata for durable entries,
but cannot prove containment or observe transient escape, absolute-path writes,
writes outside the workspace, or a symlink race that is created and removed
between snapshots. All security claims rely on the bwrap namespace and bind
configuration.

Rollback callbacks run in a separate killable subprocess. On timeout the worker
is terminated (and killed if necessary), then the parent reconciles workspace
state before persisting recovery evidence. A callback cannot mutate the parent
record after dispatch returns.
