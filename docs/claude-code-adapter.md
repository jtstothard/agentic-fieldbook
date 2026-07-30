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
with iptables-scoped egress that allows ONLY the LiteLLM proxy at
`192.168.10.252:8318`. This replaces the previous `bwrap --unshare-net` which
blocked ALL network including loopback and LAN.

### Network architecture

- **Netns name:** `fieldbook-sandbox` (managed by systemd, persists across reboot)
- **Veth pair:** `fb-sandbox0` (host, 10.200.2.1/24) <-> `fb-sandbox1` (netns, 10.200.2.2/24)
- **Scoped egress rules:**
  - FORWARD: `-i fb-sandbox0 -o eth0 -d 192.168.10.252 -p tcp --dport 8318 -j ACCEPT`
  - FORWARD: `-o fb-sandbox0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`
  - NAT POSTROUTING: `-s 10.200.2.0/24 -j MASQUERADE`
- **Sysctl:** `net.ipv4.ip_forward=1` on host

### Systemd management

The `fieldbook-sandbox.service` unit:
- Runs `systemd/fieldbook-sandbox-setup.sh` on start
- Runs `systemd/fieldbook-sandbox-teardown.sh` on stop
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

The allowlisted destination is also exposed as `allowed_egress_host` and
`allowed_egress_port` (default `192.168.10.252` and `8318`) so deployments can
keep adapter configuration aligned with their managed namespace rules. The
systemd scripts must be changed together with these values; the adapter does not
install or widen firewall rules at runtime.

### Egress verification

Verify scoped egress is working:
```bash
# Should succeed (proxy reachable)
sudo ip netns exec fieldbook-sandbox curl http://192.168.10.252:8318/health/readiness

# Should fail (other hosts blocked)
sudo ip netns exec fieldbook-sandbox curl http://example.com
```

## Workspace snapshots

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