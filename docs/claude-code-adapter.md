# Claude Code executor boundary

`ClaudeCodeAdapter` launches only through a trusted, non-symlink, root-owned,
non-group/world-writable executable inside bubblewrap. Bubblewrap is the
authoritative security boundary and is required; the host's absence of bwrap
therefore fails closed rather than falling back to an unconfined subprocess.
The real execution path requires bubblewrap (`bwrap`); this host currently has no
`bwrap` binary, so a real Claude run is intentionally blocked and fails closed.
Repository-level tests and compile checks below do not constitute a live-install
smoke test against a target Hermes installation. The Qwen benchmark timeout is
not part of the release findings.

## Scoped egress network namespace

The adapter runs Claude inside a persistent network namespace (`fieldbook-sandbox`)
with a dedicated, verified iptables chain that allows ONLY the LiteLLM proxy at
`192.168.10.252:8318`. Setup fails closed unless proxy readiness and blocked
non-proxy egress both pass. IPv6 forwarding is explicitly dropped.

### Network architecture

- **Netns name:** `fieldbook-sandbox` (managed by systemd, persists across reboot)
- **Veth pair:** `fb-sandbox0` (host, 10.200.2.1/24) <-> `fb-sandbox1` (netns, 10.200.2.2/24)
- **Scoped egress rules:** a dedicated `FIELDBOOK_SANDBOX` chain resolves the
  actual single IPv4 default-route interface, allows only proxy TCP/8318, drops
  all other IPv4 flows, and drops all IPv6 flows for the veth.
- **Sysctl:** `net.ipv4.ip_forward=1` on host

### Systemd management

The `fieldbook-sandbox.service` unit runs root-owned installed copies at
`/usr/local/libexec/fieldbook-sandbox-{setup,teardown}`. It must not execute the
mutable repository source files directly; installation should copy them as root
with mode 0755 and verify ownership before enabling the unit.
- Starts on boot (`WantedBy=multi-user.target`)
- Type: `oneshot` with `RemainAfterExit=yes`

To manage manually:
```bash
sudo systemctl start fieldbook-sandbox.service    # Create netns and rules
sudo systemctl stop fieldbook-sandbox.service     # Teardown netns and rules
sudo systemctl status fieldbook-sandbox.service   # Check status
sudo journalctl -u fieldbook-sandbox.service       # View logs
```

### Proxy authentication

The adapter injects the LiteLLM proxy credentials into the sandboxed environment:

- `ANTHROPIC_BASE_URL`: `http://192.168.10.252:8318` (NO `/v1` suffix; Claude Code appends it)
- `ANTHROPIC_API_KEY`: `sk-litellm-local-no-auth`

These are configurable via constructor parameters with the above defaults.

### Adapter configuration

```python
adapter = ClaudeCodeAdapter(
    contract=contract,
    store=store,
    executor_capabilities=("repo-write", "local-test"),
    workspace_root=workspace,
    netns_name="fieldbook-sandbox",           # Configurable netns name
    anthropic_base_url="http://192.168.10.252:8318",  # Proxy URL
    anthropic_api_key="sk-litellm-local-no-auth",     # Proxy key
)
```

The `netns_name` parameter defaults to `fieldbook-sandbox` but can be changed for
testing or alternative deployments. The `_run_process` static method wraps the
bwrap command inside `ip netns exec <netns_name>` to execute within the scoped
egress namespace.

The allowlisted destination is fixed to `192.168.10.252:8318` and the managed
namespace names are fixed to `fieldbook-sandbox` (or `fieldbook-test` for the
test seam). The adapter rejects endpoint, URL, and namespace drift rather than
treating these constructor values as decorative configuration.

### Egress verification

Verify scoped egress is working:
```bash
# Should succeed (proxy reachable)
sudo ip netns exec fieldbook-sandbox curl http://192.168.10.252:8318/health/readiness

# Should fail (other hosts blocked; setup itself checks this)
sudo ip netns exec fieldbook-sandbox curl --max-time 5 http://example.com
```

## Workspace snapshots

Repository tests use a runner seam and monkeypatch trusted tool discovery; they
prove command construction and fail-closed decisions but cannot prove a live
kernel netns, iptables, route, proxy, or systemd installation. A deployment must
install root-owned runtime scripts and separately perform the live checks above.

Workspace snapshots are supplemental evidence, not enforcement. They record
portable file type, mode, uid/gid, and file digest metadata for durable entries,
but cannot prove containment or observe transient escape, absolute-path writes,
writes outside the workspace, or a symlink race that is created and removed
between snapshots. All security claims rely on the bwrap namespace and bind
configuration plus the iptables-scoped egress rules.

## Rollback callbacks

Rollback callbacks run in a separate killable subprocess. On timeout the worker
is terminated (and killed if necessary), then the parent reconciles workspace
state before persisting recovery evidence. A callback cannot mutate the parent
record after dispatch returns.