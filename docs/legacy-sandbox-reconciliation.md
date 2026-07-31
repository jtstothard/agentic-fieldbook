# Legacy sandbox reconciliation before runtime upgrade

The installer refuses to overwrite `/usr/local/libexec/fieldbook-sandbox-{setup,teardown}` when it finds any managed evidence, including an inactive legacy deployment. This is intentional: replacing the recovery runtime before proving ownership can strand a namespace or firewall policy. The procedure below is privileged and must be performed by an operator who can recover the host console.

## 1. Stop without replacing files

From the trusted host console:

```bash
sudo systemctl stop fieldbook-sandbox.service
sudo systemctl reset-failed fieldbook-sandbox.service || true
sudo systemctl is-active fieldbook-sandbox.service   # must print inactive/failed, not active
```

Capture inspection output before deleting anything:

```bash
sudo systemctl status fieldbook-sandbox.service --no-pager
sudo ip netns list
sudo ip link show fb-sandbox0
sudo iptables -S FIELDBOOK_SANDBOX
sudo iptables -S FIELDBOOK_SANDBOX_INPUT
sudo iptables -S FORWARD | grep FIELDBOOK_SANDBOX || true
sudo iptables -S INPUT | grep FIELDBOOK_SANDBOX || true
sudo iptables -t nat -S POSTROUTING | grep '10.200.2.0/24' || true
sudo ip6tables -S FIELDBOOK_SANDBOX
sudo stat /var/lib/fieldbook-sandbox/runtime-state.conf /var/lib/fieldbook-sandbox/setup-journal.conf
```

Compare namespace inode, veth ifindexes, chain markers, addresses, and rules with the state/journal files. If identity or policy does not match the recorded Fieldbook deployment, stop: do not delete a foreign object. Escalate for manual recovery instead.

## 2. Prefer the matching teardown runtime

If the installed teardown is the version that created the state and journal, run it while the identity checks still pass:

```bash
sudo /usr/local/libexec/fieldbook-sandbox-teardown
sudo test ! -e /var/lib/fieldbook-sandbox/runtime-state.conf
sudo test ! -e /var/lib/fieldbook-sandbox/setup-journal.conf
sudo test ! -e /var/run/netns/fieldbook-sandbox
sudo test ! -e /sys/class/net/fb-sandbox0
```

A legacy deployment that has no setup journal cannot be safely removed by the new teardown (it intentionally refuses incomplete ownership evidence). In that case, use the exact values from the legacy state file and perform the equivalent removal manually only after the inspection proves every object is owned:

```bash
sudo awk -F= '/^(owner|version|netns|netns_inode|veth_host|veth_ns|host_ifindex|ns_ifindex|host_ip|ns_ip|net|uplink|chain|input_chain|input6_chain|old_ip_forward|changed_ip_forward)=/ { print }' /var/lib/fieldbook-sandbox/runtime-state.conf
sudo test "$(stat -c '%u:%g:%a' /var/lib/fieldbook-sandbox/runtime-state.conf)" = 0:0:600
sudo grep -qx 'owner=fieldbook-sandbox' /var/lib/fieldbook-sandbox/runtime-state.conf
sudo ip netns list | grep -Fx fieldbook-sandbox
sudo ip -o link show fb-sandbox0
sudo ip -o addr show dev fb-sandbox0
sudo iptables -S FIELDBOOK_SANDBOX
sudo iptables -S FIELDBOOK_SANDBOX_INPUT
sudo ip6tables -S FIELDBOOK_SANDBOX
```

The recorded namespace inode and both veth ifindexes must match the live objects; the veth peer indexes, fixed addresses, ownership marker, exact policy rules, FORWARD/INPUT jumps, NAT rule, and recorded `old_ip_forward` must also match. After those checks, remove only the exact recorded rules and objects (never flush a shared chain):

```bash
sudo iptables -D FORWARD -j FIELDBOOK_SANDBOX
sudo iptables -D INPUT -j FIELDBOOK_SANDBOX_INPUT
sudo ip6tables -D FORWARD -j FIELDBOOK_SANDBOX
sudo ip6tables -D INPUT -j FIELDBOOK_SANDBOX_INPUT6
sudo iptables -t nat -D POSTROUTING -s 10.200.2.0/24 -j MASQUERADE
sudo iptables -F FIELDBOOK_SANDBOX && sudo iptables -X FIELDBOOK_SANDBOX
sudo iptables -F FIELDBOOK_SANDBOX_INPUT && sudo iptables -X FIELDBOOK_SANDBOX_INPUT
sudo ip6tables -F FIELDBOOK_SANDBOX && sudo ip6tables -X FIELDBOOK_SANDBOX
sudo ip6tables -F FIELDBOOK_SANDBOX_INPUT6 && sudo ip6tables -X FIELDBOOK_SANDBOX_INPUT6
sudo sysctl -w net.ipv4.ip_forward=<recorded-old_ip_forward>
sudo ip link del fb-sandbox0
sudo ip netns del fieldbook-sandbox
sudo rm -f /var/lib/fieldbook-sandbox/runtime-state.conf
```

Substitute the recorded value only for `<recorded-old_ip_forward>`; if any command fails, stop and preserve the remaining state for recovery. Repeat the proof in step 3, including checking that the chains, jumps, NAT, namespace, veth, and state file are absent. This is the rollback proof that permits the upgrade; it is not a bypass for mismatched or foreign objects.

## 3. Prove rollback and clean state

After successful teardown, prove that no managed evidence remains:

```bash
sudo ip netns list | grep -Fx fieldbook-sandbox && exit 1 || true
sudo ip link show fb-sandbox0 >/dev/null 2>&1 && exit 1 || true
sudo iptables -S FIELDBOOK_SANDBOX >/dev/null 2>&1 && exit 1 || true
sudo iptables -S FIELDBOOK_SANDBOX_INPUT >/dev/null 2>&1 && exit 1 || true
sudo iptables -S FORWARD | grep -F 'FIELDBOOK_SANDBOX' && exit 1 || true
sudo iptables -S INPUT | grep -F 'FIELDBOOK_SANDBOX' && exit 1 || true
sudo iptables -t nat -S POSTROUTING | grep -F '10.200.2.0/24' && exit 1 || true
sudo ip6tables -S FIELDBOOK_SANDBOX >/dev/null 2>&1 && exit 1 || true
sudo test ! -e /var/lib/fieldbook-sandbox/runtime-state.conf
sudo test ! -e /var/lib/fieldbook-sandbox/setup-journal.conf
```

Keep the before/after command output as the rollback record. If any check finds an object, do not upgrade; the installer should continue to refuse.

## 4. Upgrade

Only after the proof above succeeds:

```bash
sudo systemd/install-fieldbook-sandbox.sh
sudo systemctl daemon-reload
sudo systemctl start fieldbook-sandbox.service
sudo systemctl status fieldbook-sandbox.service --no-pager
```

The installer is invoked with no arguments. There is no `--force` or `--migrate` flag; commit 86ed3a1 removed them. Invoke `sudo systemd/install-fieldbook-sandbox.sh` with no arguments after clean-state proof.
