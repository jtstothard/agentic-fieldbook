#!/bin/bash
# Install the sandbox runtime as root-owned files before enabling the unit.
set -Eeuo pipefail
(( EUID == 0 )) || { printf 'must run as root\n' >&2; exit 1; }
readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TARGET_DIR=/usr/local/libexec STATE_DIR=/var/lib/fieldbook-sandbox
readonly NETNS_NAME=fieldbook-sandbox VETH_HOST=fb-sandbox0
readonly CHAIN=FIELDBOOK_SANDBOX INPUT_CHAIN=FIELDBOOK_SANDBOX_INPUT INPUT6_CHAIN=FIELDBOOK_SANDBOX_INPUT6 NET=10.200.2.0/24
case "${1:-}" in
  ''|--help) printf 'Usage: %s\n' "$0"; exit 0 ;;
  *) printf 'usage: %s\n' "$0" >&2; exit 2 ;;
esac

# This check is deliberately broader than service activity.  An inactive legacy
# unit can still own the only recovery runtime and its namespace/firewall state.
managed_evidence=()
add_evidence() { managed_evidence+=("$1"); }
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet fieldbook-sandbox.service; then add_evidence 'active fieldbook-sandbox.service'; fi
[[ -e "$STATE_DIR/runtime-state.conf" ]] && add_evidence "$STATE_DIR/runtime-state.conf"
[[ -e "$STATE_DIR/setup-journal.conf" ]] && add_evidence "$STATE_DIR/setup-journal.conf"
if command -v ip >/dev/null 2>&1; then
  ip netns list 2>/dev/null | awk '{print $1}' | grep -qx "$NETNS_NAME" && add_evidence "managed namespace $NETNS_NAME"
  ip link show "$VETH_HOST" type veth >/dev/null 2>&1 && add_evidence "managed veth $VETH_HOST"
fi
if command -v iptables >/dev/null 2>&1; then
  iptables -S "$CHAIN" >/dev/null 2>&1 && add_evidence "managed IPv4 chain $CHAIN"
  iptables -S "$INPUT_CHAIN" >/dev/null 2>&1 && add_evidence "managed IPv4 chain $INPUT_CHAIN"
  iptables -S INPUT 2>/dev/null | grep -Fqx -- "-A INPUT -j $INPUT_CHAIN" && add_evidence 'managed IPv4 INPUT jump'
  iptables -S FORWARD 2>/dev/null | grep -Fqx -- "-A FORWARD -j $CHAIN" && add_evidence 'managed IPv4 FORWARD jump'
  iptables -t nat -S POSTROUTING 2>/dev/null | grep -Fqx -- "-A POSTROUTING -s $NET -j MASQUERADE" && add_evidence 'managed NAT rule'
fi
if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -S "$CHAIN" >/dev/null 2>&1 && add_evidence "managed IPv6 chain $CHAIN"
  ip6tables -S "$INPUT6_CHAIN" >/dev/null 2>&1 && add_evidence "managed IPv6 chain $INPUT6_CHAIN"
  ip6tables -S INPUT 2>/dev/null | grep -Fqx -- "-A INPUT -j $INPUT6_CHAIN" && add_evidence 'managed IPv6 INPUT jump'
  ip6tables -S FORWARD 2>/dev/null | grep -Fqx -- "-A FORWARD -j $CHAIN" && add_evidence 'managed IPv6 FORWARD jump'
fi
if (( ${#managed_evidence[@]} > 0 )); then
  printf 'refusing upgrade: managed sandbox evidence exists (%s).\n' "${managed_evidence[*]}" >&2
  printf 'Safely reconcile the legacy deployment first; see docs/legacy-sandbox-reconciliation.md.\n' >&2
  exit 1
fi
install -d -o root -g root -m 0755 "$TARGET_DIR"
for name in setup teardown; do
  install -o root -g root -m 0755 \
    "$SOURCE_DIR/fieldbook-sandbox-${name}.sh" \
    "$TARGET_DIR/fieldbook-sandbox-${name}"
done
for name in setup teardown; do
  path="$TARGET_DIR/fieldbook-sandbox-${name}"
  [[ "$(stat -c '%u:%g:%a' "$path")" == "0:0:755" ]] || {
    printf 'untrusted installed runtime: %s\n' "$path" >&2
    exit 1
  }
done
printf 'Installed root-owned Fieldbook sandbox runtimes in %s\n' "$TARGET_DIR"
