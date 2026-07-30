#!/bin/bash
# Source for the installed Fieldbook sandbox teardown runtime.
set -Eeuo pipefail
readonly IP=/usr/sbin/ip
readonly IPTABLES=/usr/sbin/iptables
readonly IP6TABLES=/usr/sbin/ip6tables
readonly SYSCTL=/usr/sbin/sysctl
readonly NETNS_NAME=fieldbook-sandbox
readonly VETH_HOST=fb-sandbox0
readonly CHAIN=FIELDBOOK_SANDBOX
readonly NET=10.200.2.0/24
readonly STATE_DIR=/var/lib/fieldbook-sandbox
readonly STATE_FILE="$STATE_DIR/runtime-state.conf"

(( EUID == 0 )) || { printf 'must run as root\n' >&2; exit 1; }

# Read runtime state file if it exists
changed_ip_forward=0
old_ip_forward=""
if [[ -r "$STATE_FILE" ]]; then
  # Source the state file (it's simple variable assignments)
  changed_ip_forward=$(grep '^changed_ip_forward=' "$STATE_FILE" | cut -d= -f2)
  old_ip_forward=$(grep '^old_ip_forward=' "$STATE_FILE" | cut -d= -f2)
  # Remove state file
  rm -f "$STATE_FILE"
fi

# Verify ownership before deletion (HIGH)
delete_netns=0
delete_veth=0
if "$IP" netns show "$NETNS_NAME" >/dev/null 2>&1; then
  # Verify namespace identity: check if it has expected veth link
  if "$IP" -n "$NETNS_NAME" link show dev fb-sandbox1 >/dev/null 2>&1; then
    delete_netns=1
  else
    printf 'WARNING: namespace %s exists but has unexpected topology (missing fb-sandbox1)\n' "$NETNS_NAME" >&2
    printf 'Failing closed: not deleting namespace\n' >&2
  fi
fi

if "$IP" link show "$VETH_HOST" type veth >/dev/null 2>&1; then
  # Verify link type and address
  link_addr=$("$IP" -o addr show dev "$VETH_HOST" | grep -oP 'inet \K[\d.]+')
  if [[ "$link_addr" == "10.200.2.1" ]]; then
    delete_veth=1
  else
    printf 'WARNING: link %s exists but has unexpected address %s\n' "$VETH_HOST" "$link_addr" >&2
    printf 'Failing closed: not deleting link\n' >&2
  fi
fi

# Delete NAT rule (not route-dependent)
"$IPTABLES" -t nat -D POSTROUTING -s "$NET" -j MASQUERADE 2>/dev/null || true

# Restore ip_forward if we changed it
if (( changed_ip_forward )) && [[ -n "$old_ip_forward" ]]; then
  "$SYSCTL" -w "net.ipv4.ip_forward=$old_ip_forward" >/dev/null 2>&1 || true
fi

# Delete only the dedicated chain and objects owned by this sandbox.
"$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IPTABLES" -F "$CHAIN" 2>/dev/null || true
"$IPTABLES" -X "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -X "$CHAIN" 2>/dev/null || true

# Delete verified network objects
if (( delete_veth )); then
  "$IP" link del "$VETH_HOST" 2>/dev/null || true
fi
if (( delete_netns )); then
  "$IP" netns del "$NETNS_NAME" 2>/dev/null || true
fi

# Clean up state directory if empty
if [[ -d "$STATE_DIR" ]]; then
  rmdir "$STATE_DIR" 2>/dev/null || true
fi

printf 'Fieldbook sandbox teardown complete\n'