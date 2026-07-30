#!/bin/bash
# Root-installed Fieldbook sandbox teardown runtime (extensionless install path).
set -Eeuo pipefail
readonly IP=/usr/sbin/ip IPTABLES=/usr/sbin/iptables IP6TABLES=/usr/sbin/ip6tables SYSCTL=/usr/sbin/sysctl
readonly NETNS_NAME=fieldbook-sandbox VETH_HOST=fb-sandbox0 VETH_NS=fb-sandbox1 HOST_IP=10.200.2.1 NS_IP=10.200.2.2
readonly CHAIN=FIELDBOOK_SANDBOX INPUT_CHAIN=FIELDBOOK_SANDBOX_INPUT INPUT6_CHAIN=FIELDBOOK_SANDBOX_INPUT6 NET=10.200.2.0/24
readonly STATE_DIR=/var/lib/fieldbook-sandbox STATE_FILE="$STATE_DIR/runtime-state.conf"
readonly MARKER=fieldbook-sandbox-ownership-marker

(( EUID == 0 )) || { printf 'must run as root\n' >&2; exit 1; }

fail_closed() { printf 'Failing closed: no object is deleted: %s\n' "$*" >&2; exit 1; }
[[ -f "$STATE_FILE" ]] || fail_closed 'runtime state is missing; nothing will be deleted (Foreign objects are never deleted)'
[[ "$(stat -c '%u:%g:%a' "$STATE_FILE" 2>/dev/null || true)" == 0:0:600 ]] || fail_closed 'runtime state ownership or mode is invalid'
grep -q '^owner=fieldbook-sandbox$' "$STATE_FILE" || fail_closed 'malformed/missing state; refusing destructive cleanup'

# Parse untrusted state as data, never by sourcing it.  Every value is fixed or
# strongly constrained, and the complete key set is required before inspection.
mapfile -t state_keys < <(sed -n 's/^\([a-z_]*\)=.*$/\1/p' "$STATE_FILE")
expected_keys=(owner version netns netns_inode veth_host veth_ns host_ifindex ns_ifindex host_ip ns_ip net uplink proxy chain input_chain input6_chain old_ip_forward changed_ip_forward)
[[ "${#state_keys[@]}" -eq "${#expected_keys[@]}" ]] || fail_closed 'runtime state is partial or has unknown lines'
for key in "${expected_keys[@]}"; do
  [[ "$(printf '%s\n' "${state_keys[@]}" | grep -cx "$key")" == 1 ]] || fail_closed "runtime state key is missing or duplicated: $key"
done
state_value() { awk -F= -v key="$1" '$1 == key { print substr($0, index($0, "=") + 1) }' "$STATE_FILE"; }
owner=$(state_value owner); version=$(state_value version); netns=$(state_value netns); netns_inode=$(state_value netns_inode)
veth_host=$(state_value veth_host); veth_ns=$(state_value veth_ns); host_ifindex=$(state_value host_ifindex); ns_ifindex=$(state_value ns_ifindex); host_ip=$(state_value host_ip); ns_ip=$(state_value ns_ip)
net=$(state_value net); uplink=$(state_value uplink); proxy=$(state_value proxy)
chain=$(state_value chain); input_chain=$(state_value input_chain); input6_chain=$(state_value input6_chain)
old_ip_forward=$(state_value old_ip_forward); changed_ip_forward=$(state_value changed_ip_forward)
[[ "$owner" == fieldbook-sandbox && "$version" == 3 && "$netns" == "$NETNS_NAME" ]] || fail_closed 'runtime state marker or version is invalid'
[[ "$netns_inode" =~ ^[0-9]+$ && "$host_ifindex" =~ ^[0-9]+$ && "$ns_ifindex" =~ ^[0-9]+$ ]] || fail_closed 'runtime identity state is invalid'
[[ "$veth_host" == "$VETH_HOST" && "$veth_ns" == "$VETH_NS" && "$host_ip" == "$HOST_IP/24" && "$ns_ip" == "$NS_IP/24" ]] || fail_closed 'runtime topology in state is not managed topology'
[[ "$net" == "$NET" && "$uplink" =~ ^[a-zA-Z0-9_.:-]+$ && "$proxy" =~ ^192\.168\.10\.252:8318$ ]] || fail_closed 'runtime route or proxy state is invalid'
[[ "$chain" == "$CHAIN" && "$input_chain" == "$INPUT_CHAIN" && "$input6_chain" == "$INPUT6_CHAIN" && "$old_ip_forward" =~ ^[01]$ && "$changed_ip_forward" == 1 ]] || fail_closed 'runtime policy state is invalid'

# The complete topology and exact policy are checked before the first deletion.
# A mismatch aborts without even removing a jump or NAT rule.
iptables_chain() { "$IPTABLES" -S "$1" 2>/dev/null; }
ip6_chain() { "$IP6TABLES" -S "$1" 2>/dev/null; }
require_line() { grep -Fqx -- "$2" <<<"$1"; }
[[ "$("$IP" netns list | awk '{print $1}' | grep -cx "$NETNS_NAME")" == 1 ]] || fail_closed 'managed namespace is absent or ambiguous'
actual_netns_inode=$(stat -Lc '%i' "/var/run/netns/$NETNS_NAME" 2>/dev/null || true)
[[ "$actual_netns_inode" == "$netns_inode" ]] || fail_closed 'managed namespace inode does not match'
"$IP" link show "$VETH_HOST" type veth >/dev/null 2>&1 || fail_closed 'managed host veth is absent or not veth'
actual_host_ifindex=$("$IP" -o link show dev "$VETH_HOST" | awk -F: '{print $1}')
[[ "$actual_host_ifindex" == "$host_ifindex" ]] || fail_closed 'managed host veth ifindex does not match'
"$IP" -o addr show dev "$VETH_HOST" | grep -Eq "inet $HOST_IP/24( |$)" || fail_closed 'managed host veth address 10.200.2.1 does not match'
"$IP" -n "$NETNS_NAME" link show dev "$VETH_NS" >/dev/null 2>&1 || fail_closed 'managed namespace peer is absent'
actual_ns_ifindex=$("$IP" -n "$NETNS_NAME" -o link show dev "$VETH_NS" | awk -F: '{print $1}')
[[ "$actual_ns_ifindex" == "$ns_ifindex" ]] || fail_closed 'managed namespace peer ifindex does not match'
"$IP" -o link show dev "$VETH_HOST" | grep -Eq "@if${ns_ifindex}([ :]|$)" || fail_closed 'host veth peer linkage does not match'
"$IP" -n "$NETNS_NAME" -o link show dev "$VETH_NS" | grep -Eq "@if${host_ifindex}([ :]|$)" || fail_closed 'namespace veth peer linkage does not match'
"$IP" -n "$NETNS_NAME" -o addr show dev "$VETH_NS" | grep -Eq "inet $NS_IP/24( |$)" || fail_closed 'managed namespace address does not match'
"$IP" -n "$NETNS_NAME" route show default | grep -Fqx "default via $HOST_IP dev $VETH_NS" || fail_closed 'managed namespace route does not match'
"$IP" link show dev "$uplink" >/dev/null 2>&1 || fail_closed 'recorded uplink is absent'

require_line "$(iptables_chain "$CHAIN")" "-A $CHAIN -m comment --comment $MARKER" || fail_closed 'IPv4 chain marker mismatch'
require_line "$(iptables_chain "$INPUT_CHAIN")" "-A $INPUT_CHAIN -m comment --comment $MARKER" || fail_closed 'INPUT chain marker mismatch'
require_line "$(ip6_chain "$CHAIN")" "-A $CHAIN -m comment --comment $MARKER" || fail_closed 'IPv6 chain marker mismatch'
for rule in "-A FORWARD -j $CHAIN" "-A INPUT -j $INPUT_CHAIN"; do
  jump_chain=FORWARD
  [[ "$rule" == "-A INPUT "* ]] && jump_chain=INPUT
  "$IPTABLES" -S "$jump_chain" 2>/dev/null | grep -Fqx -- "$rule" || fail_closed "owned jump is missing or changed: $rule"
done
"$IP6TABLES" -S FORWARD 2>/dev/null | grep -Fqx -- "-A FORWARD -j $CHAIN" || fail_closed 'owned IPv6 jump is missing or changed'
"$IPTABLES" -t nat -S POSTROUTING 2>/dev/null | grep -Fqx -- "-A POSTROUTING -s $NET -j MASQUERADE" || fail_closed 'owned NAT rule is missing or changed'
# Validate the complete managed policy, not merely its marker, before deletion.
for rule in \
  "-A $CHAIN -m comment --comment $MARKER" \
  "-A $CHAIN ! -i $VETH_HOST ! -o $VETH_HOST -j RETURN" \
  "-A $CHAIN -i $VETH_HOST -o $uplink -s $NET -d ${proxy%:*} -p tcp --dport ${proxy##*:} -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT" \
  "-A $CHAIN -o $VETH_HOST -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" \
  "-A $CHAIN -i $VETH_HOST -o $uplink -s $NET -j DROP" \
  "-A $CHAIN -j DROP"; do
  require_line "$(iptables_chain "$CHAIN")" "$rule" || fail_closed "IPv4 managed policy mismatch: $rule"
done
mapfile -t input_rules < <("$IPTABLES" -S "$INPUT_CHAIN")
[[ "${#input_rules[@]}" == 6 ]] || fail_closed 'IPv4 INPUT policy has extra or missing rules'
for rule in "-A $INPUT_CHAIN -m comment --comment $MARKER" "-A $INPUT_CHAIN ! -i $VETH_HOST -j RETURN" "-A $INPUT_CHAIN -i $VETH_HOST -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" "-A $INPUT_CHAIN -i $VETH_HOST -d $HOST_IP -j DROP" "-A $INPUT_CHAIN -i $VETH_HOST -j DROP"; do
  require_line "$(printf '%s\n' "${input_rules[@]}")" "$rule" || fail_closed "IPv4 INPUT policy mismatch: $rule"
done
for rule in \
  "-A $CHAIN -m comment --comment $MARKER" \
  "-A $CHAIN ! -i $VETH_HOST ! -o $VETH_HOST -j RETURN" \
  "-A $CHAIN -i $VETH_HOST -j DROP" \
  "-A $CHAIN -o $VETH_HOST -j DROP" \
  "-A $CHAIN -j DROP"; do
  require_line "$(ip6_chain "$CHAIN")" "$rule" || fail_closed "IPv6 managed policy mismatch: $rule"
done
mapfile -t input6_rules < <("$IP6TABLES" -S "$INPUT6_CHAIN")
[[ "${#input6_rules[@]}" == 5 ]] || fail_closed 'IPv6 INPUT policy has extra or missing rules'
for rule in "-A $INPUT6_CHAIN -m comment --comment $MARKER" "-A $INPUT6_CHAIN ! -i $VETH_HOST -j RETURN" "-A $INPUT6_CHAIN -i $VETH_HOST -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" "-A $INPUT6_CHAIN -i $VETH_HOST -j DROP"; do
  require_line "$(printf '%s\n' "${input6_rules[@]}")" "$rule" || fail_closed "IPv6 INPUT policy mismatch: $rule"
done

rc=0
"$IPTABLES" -D FORWARD -j "$CHAIN" || rc=1
"$IPTABLES" -D INPUT -j "$INPUT_CHAIN" || rc=1
"$IP6TABLES" -D FORWARD -j "$CHAIN" || rc=1
"$IP6TABLES" -D INPUT -j "$INPUT6_CHAIN" || rc=1
"$IPTABLES" -t nat -D POSTROUTING -s "$NET" -j MASQUERADE || rc=1
"$IPTABLES" -F "$CHAIN" || rc=1; "$IPTABLES" -X "$CHAIN" || rc=1
"$IPTABLES" -F "$INPUT_CHAIN" || rc=1; "$IPTABLES" -X "$INPUT_CHAIN" || rc=1
"$IP6TABLES" -F "$CHAIN" || rc=1; "$IP6TABLES" -X "$CHAIN" || rc=1
"$IP6TABLES" -F "$INPUT6_CHAIN" || rc=1; "$IP6TABLES" -X "$INPUT6_CHAIN" || rc=1
(( changed_ip_forward == 1 )) && "$SYSCTL" -w "net.ipv4.ip_forward=$old_ip_forward" >/dev/null || rc=1
"$IP" link del "$VETH_HOST" || rc=1
"$IP" netns del "$NETNS_NAME" || rc=1
if (( rc == 0 )); then
  rm -f "$STATE_FILE" || rc=1
  rmdir "$STATE_DIR" 2>/dev/null || true
else
  printf 'teardown incomplete; runtime state retained for retry\n' >&2
fi
(( rc == 0 )) || exit 1
printf 'Fieldbook sandbox teardown complete\n'
