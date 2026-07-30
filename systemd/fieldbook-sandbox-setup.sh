#!/bin/bash
# Source for the installed Fieldbook sandbox setup runtime.
# The systemd unit must execute a root-owned copy under /usr/local/libexec.
set -Eeuo pipefail

readonly IP=/usr/sbin/ip
readonly IPTABLES=/usr/sbin/iptables
readonly IP6TABLES=/usr/sbin/ip6tables
readonly SYSCTL=/usr/sbin/sysctl
readonly CURL=/usr/bin/curl
readonly NETNS_NAME=fieldbook-sandbox
readonly VETH_HOST=fb-sandbox0
readonly VETH_NS=fb-sandbox1
readonly HOST_IP=10.200.2.1
readonly NS_IP=10.200.2.2
readonly PROXY_HOST=192.168.10.252
readonly PROXY_PORT=8318
readonly CHAIN=FIELDBOOK_SANDBOX
readonly NET=10.200.2.0/24

created_netns=0
created_veth=0
rules_installed=0

fail() { printf 'fieldbook sandbox setup failed: %s\n' "$*" >&2; exit 1; }
cleanup() {
  local status=$?
  trap - EXIT
  if (( status != 0 )); then
    "$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
    "$IPTABLES" -F "$CHAIN" 2>/dev/null || true
    "$IPTABLES" -X "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -X "$CHAIN" 2>/dev/null || true
    "$IP" link del "$VETH_HOST" 2>/dev/null || true
    "$IP" netns del "$NETNS_NAME" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT

(( EUID == 0 )) || fail "must run as root"
for tool in "$IP" "$IPTABLES" "$IP6TABLES" "$SYSCTL" "$CURL"; do
  [[ -x "$tool" ]] || fail "required trusted tool missing: $tool"
done

# Remove only our owned state, tolerating partial previous setup.
"$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IPTABLES" -F "$CHAIN" 2>/dev/null || true
"$IPTABLES" -X "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -X "$CHAIN" 2>/dev/null || true
"$IP" link del "$VETH_HOST" 2>/dev/null || true
"$IP" netns del "$NETNS_NAME" 2>/dev/null || true

# Resolve the actual default-route interface and reject an ambiguous topology.
mapfile -t routes < <("$IP" -o -4 route show default)
(( ${#routes[@]} == 1 )) || fail "expected exactly one IPv4 default route"
uplink="${routes[0]#* dev }"
uplink="${uplink%% *}"
[[ -n "$uplink" && "$uplink" != "dev" && "$uplink" != "via" ]] || fail "could not parse default-route interface"
"$IP" link show dev "$uplink" >/dev/null || fail "default-route interface is unavailable"

"$IP" netns add "$NETNS_NAME"
created_netns=1
"$IP" link add "$VETH_HOST" type veth peer name "$VETH_NS"
created_veth=1
"$IP" link set "$VETH_NS" netns "$NETNS_NAME"
"$IP" addr add "$HOST_IP/24" dev "$VETH_HOST"
"$IP" link set "$VETH_HOST" up
"$IP" -n "$NETNS_NAME" addr add "$NS_IP/24" dev "$VETH_NS"
"$IP" -n "$NETNS_NAME" link set "$VETH_NS" up
"$IP" -n "$NETNS_NAME" link set lo up
"$IP" -n "$NETNS_NAME" route add default via "$HOST_IP"
"$SYSCTL" -w net.ipv4.ip_forward=1 >/dev/null

# Dedicated chain: only the proxy flow and established return traffic are allowed.
"$IPTABLES" -N "$CHAIN"
"$IPTABLES" -A FORWARD -j "$CHAIN"
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -j DROP
"$IPTABLES" -A "$CHAIN" -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
"$IPTABLES" -A "$CHAIN" -j DROP
# IPv6 must never become an alternate path.
"$IP6TABLES" -N "$CHAIN"
"$IP6TABLES" -A FORWARD -j "$CHAIN"
"$IP6TABLES" -A "$CHAIN" -i "$VETH_HOST" -j DROP
"$IP6TABLES" -A "$CHAIN" -o "$VETH_HOST" -j DROP
"$IP6TABLES" -A "$CHAIN" -j DROP
"$IPTABLES" -t nat -A POSTROUTING -s "$NET" -o "$uplink" -j MASQUERADE
rules_installed=1

# Verify exact policy, route, readiness, and a blocked alternate destination.
"$IP" -n "$NETNS_NAME" route get "$PROXY_HOST" | grep -Eq "dev $VETH_NS"
"$IPTABLES" -S "$CHAIN" | grep -F -- "-d $PROXY_HOST -p tcp --dport $PROXY_PORT" >/dev/null
"$IPTABLES" -S "$CHAIN" | grep -F -- "-i $VETH_HOST -o $uplink" >/dev/null
"$IP6TABLES" -S "$CHAIN" | grep -F -- "-i $VETH_HOST" >/dev/null
"$IP" netns exec "$NETNS_NAME" "$CURL" --fail --silent --show-error --connect-timeout 5 --max-time 10 \
  "http://${PROXY_HOST}:${PROXY_PORT}/health/readiness" >/dev/null \
  || fail "proxy readiness check failed"
if "$IP" netns exec "$NETNS_NAME" "$CURL" --connect-timeout 3 --max-time 5 \
    --silent --output /dev/null http://example.com/; then
  fail "non-proxy egress is reachable"
fi

trap - EXIT
printf 'Fieldbook sandbox ready: %s via %s (%s:%s only)\n' "$NETNS_NAME" "$uplink" "$PROXY_HOST" "$PROXY_PORT"
