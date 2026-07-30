#!/bin/bash
# Root-installed Fieldbook scoped-egress runtime.  This file is intentionally
# extensionless after installation; never execute a mutable checkout copy.
set -Eeuo pipefail
readonly IP=/usr/sbin/ip IPTABLES=/usr/sbin/iptables IP6TABLES=/usr/sbin/ip6tables SYSCTL=/usr/sbin/sysctl CURL=/usr/bin/curl
readonly NETNS_NAME=fieldbook-sandbox VETH_HOST=fb-sandbox0 VETH_NS=fb-sandbox1
readonly HOST_IP=10.200.2.1 NS_IP=10.200.2.2 PROXY_HOST=192.168.10.252 PROXY_PORT=8318
readonly CHAIN=FIELDBOOK_SANDBOX INPUT_CHAIN=FIELDBOOK_SANDBOX_INPUT NET=10.200.2.0/24
readonly STATE_DIR=/var/lib/fieldbook-sandbox STATE_FILE="$STATE_DIR/runtime-state.conf" STATE_OWNER=root:root
readonly MARKER=fieldbook-sandbox-ownership-marker
changed_ip_forward=0
state_created=0
fail() { printf 'fieldbook sandbox setup failed: %s\n' "$*" >&2; exit 1; }
owned_state() { [[ -f "$STATE_FILE" && $(stat -c '%u:%g:%a' "$STATE_FILE" 2>/dev/null || true) == 0:0:600 ]] || return 1; grep -qx 'owner=fieldbook-sandbox' "$STATE_FILE"; }
object_exists() {
  "$IP" netns list 2>/dev/null | awk '{print $1}' | grep -qx "$NETNS_NAME" ||
  "$IP" link show "$VETH_HOST" >/dev/null 2>&1 ||
  "$IPTABLES" -S "$CHAIN" >/dev/null 2>&1 ||
  "$IP6TABLES" -S "$CHAIN" >/dev/null 2>&1 ||
  "$IPTABLES" -t nat -S POSTROUTING 2>/dev/null | grep -F -- "-s $NET -j MASQUERADE" >/dev/null ||
  "$IPTABLES" -S INPUT 2>/dev/null | grep -F -- "-j $INPUT_CHAIN" >/dev/null
}
cleanup() {
  local status=$? rc=0
  trap - EXIT
  (( status == 0 )) && exit 0
  # Never destroy a collision.  Rollback is allowed only after our atomic marker
  # exists and every object still matches the identity recorded in it.
  if ! owned_state; then exit "$status"; fi
  "$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || rc=1
  "$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || rc=1
  "$IPTABLES" -D INPUT -j "$INPUT_CHAIN" 2>/dev/null || rc=1
  "$IPTABLES" -t nat -D POSTROUTING -s "$NET" -j MASQUERADE 2>/dev/null || rc=1
  "$IPTABLES" -F "$CHAIN" 2>/dev/null || rc=1; "$IPTABLES" -X "$CHAIN" 2>/dev/null || rc=1
  "$IP6TABLES" -F "$CHAIN" 2>/dev/null || rc=1; "$IP6TABLES" -X "$CHAIN" 2>/dev/null || rc=1
  "$IPTABLES" -F "$INPUT_CHAIN" 2>/dev/null || rc=1; "$IPTABLES" -X "$INPUT_CHAIN" 2>/dev/null || rc=1
  if (( changed_ip_forward )); then "$SYSCTL" -w "net.ipv4.ip_forward=$old_ip_forward" >/dev/null || rc=1; fi
  "$IP" link del "$VETH_HOST" >/dev/null 2>&1 || rc=1
  "$IP" netns del "$NETNS_NAME" >/dev/null 2>&1 || rc=1
  if (( rc == 0 )); then rm -f "$STATE_FILE" || rc=1; fi
  exit $(( rc == 0 ? status : 1 ))
}
trap cleanup EXIT
(( EUID == 0 )) || fail 'must run as root'
for tool in "$IP" "$IPTABLES" "$IP6TABLES" "$SYSCTL" "$CURL"; do [[ -x "$tool" ]] || fail "required trusted tool missing: $tool"; done
install -d -o root -g root -m 700 "$STATE_DIR"
if owned_state || object_exists; then fail 'managed or foreign sandbox objects already exist; refusing collision cleanup'; fi
mapfile -t routes < <("$IP" -o -4 route show default)
(( ${#routes[@]} == 1 )) || fail 'expected exactly one IPv4 default route'
uplink="${routes[0]#* dev }"; uplink="${uplink%% *}"
[[ -n "$uplink" && "$uplink" != dev && "$uplink" != via ]] || fail 'could not parse default-route interface'
"$IP" link show dev "$uplink" >/dev/null || fail 'default-route interface unavailable'
old_ip_forward="$("$SYSCTL" -n net.ipv4.ip_forward)"
# The marker is durable before the first namespace/firewall mutation.
tmp_state="$STATE_DIR/.runtime-state.$$"
( umask 077; printf '%s\n' 'owner=fieldbook-sandbox' 'version=3' "netns=$NETNS_NAME" "veth_host=$VETH_HOST" "veth_ns=$VETH_NS" "host_ip=$HOST_IP/24" "ns_ip=$NS_IP/24" "net=$NET" "uplink=$uplink" "proxy=$PROXY_HOST:$PROXY_PORT" "chain=$CHAIN" "input_chain=$INPUT_CHAIN" "old_ip_forward=$old_ip_forward" "changed_ip_forward=1" ) >"$tmp_state"
chown root:root "$tmp_state"; chmod 600 "$tmp_state"; mv -f "$tmp_state" "$STATE_FILE"; state_created=1
"$IP" netns add "$NETNS_NAME"
"$IP" link add "$VETH_HOST" type veth peer name "$VETH_NS"
"$IP" link set "$VETH_NS" netns "$NETNS_NAME"
"$IP" addr add "$HOST_IP/24" dev "$VETH_HOST"; "$IP" link set "$VETH_HOST" up
"$IP" -n "$NETNS_NAME" addr add "$NS_IP/24" dev "$VETH_NS"; "$IP" -n "$NETNS_NAME" link set "$VETH_NS" up; "$IP" -n "$NETNS_NAME" link set lo up
"$IP" -n "$NETNS_NAME" route add default via "$HOST_IP"
"$SYSCTL" -w net.ipv4.ip_forward=1 >/dev/null; changed_ip_forward=1
"$IPTABLES" -N "$CHAIN"; "$IPTABLES" -A "$CHAIN" -m comment --comment "$MARKER"
"$IPTABLES" -A "$CHAIN" ! -i "$VETH_HOST" ! -o "$VETH_HOST" -j RETURN
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
"$IPTABLES" -A "$CHAIN" -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -j DROP
"$IPTABLES" -A "$CHAIN" -j DROP
"$IPTABLES" -I FORWARD 1 -j "$CHAIN"
"$IPTABLES" -N "$INPUT_CHAIN"; "$IPTABLES" -A "$INPUT_CHAIN" -m comment --comment "$MARKER"
"$IPTABLES" -A "$INPUT_CHAIN" ! -i "$VETH_HOST" -j RETURN
"$IPTABLES" -A "$INPUT_CHAIN" -i "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
"$IPTABLES" -A "$INPUT_CHAIN" -i "$VETH_HOST" -d "$HOST_IP" -j DROP
"$IPTABLES" -A "$INPUT_CHAIN" -i "$VETH_HOST" -j DROP
"$IPTABLES" -I INPUT 1 -j "$INPUT_CHAIN"
"$IP6TABLES" -N "$CHAIN"; "$IP6TABLES" -A "$CHAIN" -m comment --comment "$MARKER"; "$IP6TABLES" -A "$CHAIN" ! -i "$VETH_HOST" ! -o "$VETH_HOST" -j RETURN; "$IP6TABLES" -A "$CHAIN" -i "$VETH_HOST" -j DROP; "$IP6TABLES" -A "$CHAIN" -o "$VETH_HOST" -j DROP; "$IP6TABLES" -I FORWARD 1 -j "$CHAIN"
"$IPTABLES" -t nat -A POSTROUTING -s "$NET" -j MASQUERADE
"$IP" -n "$NETNS_NAME" route get "$PROXY_HOST" | grep -Eq "dev $VETH_NS"
"$IPTABLES" -S "$CHAIN" | grep -F -- "-d $PROXY_HOST -p tcp --dport $PROXY_PORT" >/dev/null
"$IPTABLES" -S INPUT | grep -F -- "-j $INPUT_CHAIN" >/dev/null
"$IP" netns exec "$NETNS_NAME" "$CURL" --fail --silent --show-error --connect-timeout 5 --max-time 10 "http://${PROXY_HOST}:${PROXY_PORT}/health/readiness" >/dev/null || fail 'proxy readiness check failed'
if "$IP" netns exec "$NETNS_NAME" "$CURL" --connect-timeout 3 --max-time 5 --silent --output /dev/null http://example.com/; then fail 'non-proxy egress is reachable'; fi
trap - EXIT
printf 'Fieldbook sandbox ready: %s via %s (%s:%s only)\n' "$NETNS_NAME" "$uplink" "$PROXY_HOST" "$PROXY_PORT"
