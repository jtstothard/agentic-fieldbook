# Fieldbook Sandbox Boundary Model

## Overview

The Fieldbook scoped-egress sandbox provides a hardened network boundary for autonomous AI agents, restricting egress to a single approved proxy endpoint while blocking all other network access. This boundary is enforced through a layered defense using Linux network namespaces, veth pairs, and iptables.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host System                               │
│                                                                  │
│  ┌──────────────────┐          ┌──────────────────────────────┐ │
│  │  fieldbook-sandbox│          │   Default Uplink (e.g., eth0)  │ │
│  │  Network Namespace│          │                               │ │
│  │                  │          │   Internet                     │ │
│  │  ┌──────────────┐│          │   ┌────────────────────┐      │ │
│  │  │ fb-sandbox1  ││          │   │  Proxy Server      │      │ │
│  │  │ 10.200.2.2   ││◄────────┼──►│  192.168.10.252    │      │ │
│  │  └──────────────┘│          │   │  :8318              │      │ │
│  │         │          │          │   └────────────────────┘      │ │
│  └─────────┼──────────┘          └──────────────────────────────┘ │
│            │                                                        │
│            │ veth pair                                             │
│            │                                                        │
│  ┌─────────▼──────────┐                                            │
│  │    fb-sandbox0     │                                            │
│  │    10.200.2.1      │                                            │
│  └────────────────────┘                                            │
│                    │                                                │
│                    │ iptables FORWARD chain                        │
│                    │ (inserted at position 1)                       │
│                    ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │           FIELDBOOK_SANDBOX Chain                             │ │
│  │                                                              │ │
│  │  1. Non-sandbox traffic: RETURN                              │ │
│  │  2. Host-gateway deny: DROP to 10.200.2.1                    │ │
│  │  3. Proxy allow: ACCEPT to 192.168.10.252:8318               │ │
│  │  4. Egress deny: DROP all other sandbox egress               │ │
│  │  5. Return traffic: ACCEPT RELATED,ESTABLISHED                │ │
│  │  6. Terminal drop: DROP all remaining packets                │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Security Boundaries

### 1. Network Isolation

The sandbox runs in a dedicated Linux network namespace (`fieldbook-sandbox`) with its own network stack. This provides:

- **Process isolation**: Sandbox processes have separate routing tables, firewall rules, and network devices
- **Interface scoping**: Only the veth pair (`fb-sandbox0`/`fb-sandbox1`) connects the sandbox to the host
- **Address control**: Fixed IP addresses (10.200.2.1 host, 10.200.2.2 sandbox) prevent address drift

### 2. Traffic Scoping

The `FIELDBOOK_SANDBOX` iptables chain applies ONLY to sandbox traffic:

```bash
# Non-sandbox traffic returns immediately
iptables -A FIELDBOOK_SANDBOX ! -i fb-sandbox0 ! -o fb-sandbox0 -j RETURN

# Host-gateway exposure deny
iptables -A FIELDBOOK_SANDBOX -i fb-sandbox0 -d 10.200.2.1 -j DROP
```

**Critical invariant**: Non-sandbox traffic never reaches the DROP rules. If `fb-sandbox0` is not involved, the chain returns immediately.

### 3. Forward Chain Ordering

The jump to `FIELDBOOK_SANDBOX` is inserted at the earliest position in the FORWARD chain:

```bash
iptables -I FORWARD 1 -j FIELDBOOK_SANDBOX
```

This prevents bypass by earlier ACCEPT rules. Any pre-existing rule at position 1 is recorded and restored on teardown.

### 4. Egress Allowlist

Only one destination is permitted: the proxy server at 192.168.10.252:8318.

```bash
# Allow NEW and ESTABLISHED connections to proxy
iptables -A FIELDBOOK_SANDBOX -i fb-sandbox0 -o <uplink> \
  -s 10.200.2.0/24 -d 192.168.10.252 -p tcp --dport 8318 \
  -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT

# Deny all other egress
iptables -A FIELDBOOK_SANDBOX -i fb-sandbox0 -o <uplink> -s 10.200.2.0/24 -j DROP
```

**Critical invariant**: All egress from sandbox is dropped except the proxy flow.

### 5. Return Traffic

Established and related connections are allowed back to the sandbox:

```bash
iptables -A FIELDBOOK_SANDBOX -o fb-sandbox0 \
  -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

### 6. IPv6 Hardening

IPv6 is explicitly blocked to prevent alternate egress paths:

```bash
ip6tables -N FIELDBOOK_SANDBOX
ip6tables -A FIELDBOOK_SANDBOX ! -i fb-sandbox0 ! -o fb-sandbox0 -j RETURN
ip6tables -A FIELDBOOK_SANDBOX -i fb-sandbox0 -j DROP
ip6tables -A FIELDBOOK_SANDBOX -o fb-sandbox0 -j DROP
ip6tables -A FIELDBOOK_SANDBOX -j DROP
```

### 7. Host-Gateway Protection

The sandbox cannot reach host-local services listening on 10.200.2.1:

```bash
iptables -A FIELDBOOK_SANDBOX -i fb-sandbox0 -d 10.200.2.1 -j DROP
```

This rule is scoped to veth ingress and does not block proxy or established return traffic.

## Lifecycle Management

### State Persistence

Runtime state is recorded in a root-owned file (`/var/lib/fieldbook-sandbox/runtime-state.conf`):

```bash
changed_ip_forward=1
old_ip_forward=0
```

This enables exact restoration of host state on teardown.

### Safe Failure Paths

On setup failure, the cleanup function:

1. Restores any displaced FORWARD rule
2. Deletes the exact NAT rule added by this service
3. Restores `ip_forward` to its prior value
4. Deletes veth pair and namespace

### Teardown Guarantees

Teardown:

1. Reads state file to get prior `ip_forward` value
2. Deletes NAT rule (not route-dependent: `-s 10.200.2.0/24 -j MASQUERADE`)
3. Restores `ip_forward` only if this service changed it
4. Verifies namespace and veth topology before deletion
5. Fails closed on topology mismatch instead of blind deletion
6. Cleans up state file and directory

### NAT Rule Exactness

The NAT rule is **not** route-dependent. It matches only on source network:

```bash
iptables -t nat -A POSTROUTING -s 10.200.2.0/24 -j MASQUERADE
```

This ensures:
- No interface dependency (uplink can change)
- No duplicate NAT accumulation on repeated start/stop
- Exact deletion on teardown without route rediscovery

## Security Invariants

The sandbox boundary is defined by these invariant tests:

1. **Chain scoping**: Non-sandbox traffic returns, never drops
2. **No unconditional DROP**: Every DROP is scoped to sandbox traffic
3. **Ownership marker**: Chain contains ownership comment for verification
4. **Forward ordering**: Jump at position 1, cannot be bypassed
5. **Displaced rule tracking**: Pre-existing FORWARD rules are restored
6. **Pre-state recording**: ip_forward recorded before mutation
7. **State persistence**: Runtime state written to root-owned file
8. **NAT exactness**: NAT rule not route-dependent, deleted exactly
9. **Cleanup deletes NAT**: Failure path deletes NAT rule
10. **Restore ip_forward**: Both cleanup and teardown restore ip_forward
11. **Verify before delete**: Namespace/veth verified before deletion
12. **Fail closed**: Topology mismatch prevents blind deletion
13. **Host-gateway deny**: veth ingress to 10.200.2.1 blocked
14. **No accumulation**: Repeated start/stop doesn't accumulate NAT rules
15. **State cleanup**: Teardown removes state file

See `tests/test_sandbox_firewall_lifecycle.py` for adversarial tests of each invariant.

## Verification

### Static Verification

```bash
# Bash syntax check
bash -n systemd/fieldbook-sandbox-setup.sh
bash -n systemd/fieldbook-sandbox-teardown.sh

# Adversarial invariant tests (no host mutation required)
python3 -m pytest tests/test_sandbox_firewall_lifecycle.py -v
```

### Runtime Verification

The setup script performs live verification:

1. Route verification: confirms proxy route uses fb-sandbox1
2. Chain verification: confirms proxy rule exists in FIELDBOOK_SANDBOX
3. Interface verification: confirms uplink interface is used
4. Host-gateway verification: confirms deny rule exists
5. Ordering verification: confirms FORWARD jump is at position 1
6. IPv6 verification: confirms IPv6 blocking rules exist
7. Proxy readiness: health check to proxy `/health/readiness`
8. Egress blocking: confirms non-proxy destination (example.com) is unreachable

### Failure Modes

The sandbox fails closed on all errors:

- Setup failure: rolls back all mutations, exits with error
- Route ambiguity: rejects ambiguous topology (multiple default routes)
- Missing tools: exits with clear error message
- Not root: exits with clear error message
- Proxy unreachable: fails with explicit message
- Egress leak detected: fails with explicit message

## Deployment Notes

### Installation

The scripts are installed as root-owned executables under `/usr/local/libexec`:

```bash
sudo install -o root -g root -m 755 \
  systemd/fieldbook-sandbox-setup.sh /usr/local/libexec/
sudo install -o root -g root -m 755 \
  systemd/fieldbook-sandbox-teardown.sh /usr/local/libexec/
```

### Systemd Unit

The systemd unit references the installed copy:

```ini
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/libexec/fieldbook-sandbox-setup.sh
ExecStop=/usr/local/libexec/fieldbook-sandbox-teardown.sh
```

### Requirements

- Linux with network namespace support
- iptables and ip6tables
- iproute2 (ip command)
- sysctl
- curl (for proxy health check)
- Root privileges (required for netns and iptables manipulation)

### State Directory

The runtime state directory `/var/lib/fieldbook-sandbox` is created with:

- Ownership: root:root
- Permissions: 700 (owner read/write/execute only)

The state file contains only boolean flags and string values, no secrets.

## Limitations

1. **Single uplink**: Requires exactly one IPv4 default route
2. **Fixed addressing**: Uses hardcoded 10.200.2.0/24 network
3. **Proxy dependency**: Requires proxy at 192.168.10.252:8318 with `/health/readiness`
4. **Root required**: Cannot run as unprivileged user
5. **Linux only**: No support for other operating systems
6. **IPv4 focus**: IPv6 is blocked, not scoped

## Threat Model

The sandbox boundary is designed to contain these threats:

- **Arbitrary egress**: Blocked by allowlist and terminal DROP
- **Proxy bypass**: Blocked by egress deny and NAT scoping
- **Host access**: Blocked by host-gateway deny and namespace isolation
- **Rule bypass**: Blocked by forward chain ordering
- **State leakage**: Blocked by exact cleanup and state restoration
- **Namespace reuse**: Blocked by ownership verification

The sandbox does NOT protect against:

- **Compromised proxy**: If the proxy is malicious, it can forward any traffic
- **Side channels**: CPU/cache timing, acoustic, power analysis, etc.
- **Physical access**: Direct memory access, DMA attacks
- **Kernel exploits**: Vulnerabilities in network namespace implementation

## References

- [Linux Network Namespaces Documentation](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
- [iptables-extensions Documentation](https://man7.org/linux/man-pages/man8/iptables-extensions.8.html)
- [conntrack Documentation](https://man7.org/linux/man-pages/man8/conntrack.8.html)
- [fieldbook-sandbox-setup.sh](../systemd/fieldbook-sandbox-setup.sh)
- [fieldbook-sandbox-teardown.sh](../systemd/fieldbook-sandbox-teardown.sh)
- [test_sandbox_firewall_lifecycle.py](../tests/test_sandbox_firewall_lifecycle.py)