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
readonly STATE_DIR=/var/lib/fieldbook-sandbox
readonly STATE_FILE="$STATE_DIR/runtime-state.conf"
readonly STATE_OWNER=root:root

created_netns=0
created_veth=0
rules_installed=0
displaced_rule=""
changed_ip_forward=0
old_ip_forward=""

fail() { printf 'fieldbook sandbox setup failed: %s\n' "$*" >&2; exit 1; }

cleanup() {
  local status=$?
  trap - EXIT
  if (( status != 0 )); then
    # Restore any displaced FORWARD rule
    if [[ -n "$displaced_rule" ]]; then
      "$IPTABLES" $displaced_rule 2>/dev/null || true
    fi
    # Flush and delete chain
    "$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
    "$IPTABLES" -F "$CHAIN" 2>/dev/null || true
    "$IPTABLES" -X "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
    "$IP6TABLES" -X "$CHAIN" 2>/dev/null || true
    # Delete NAT rule if installed (not route-dependent)
    "$IPTABLES" -t nat -D POSTROUTING -s "$NET" -j MASQUERADE 2>/dev/null || true
    # Restore ip_forward if we changed it
    if (( changed_ip_forward )); then
      "$SYSCTL" -w "net.ipv4.ip_forward=$old_ip_forward" >/dev/null 2>&1 || true
    fi
    # Cleanup network objects
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

# Create state directory with correct ownership
if [[ ! -d "$STATE_DIR" ]]; then
  mkdir -p "$STATE_DIR" || fail "cannot create state directory: $STATE_DIR"
fi
chown "$STATE_OWNER" "$STATE_DIR"
chmod 700 "$STATE_DIR"

# Remove only our owned state, tolerating partial previous setup.
"$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IPTABLES" -F "$CHAIN" 2>/dev/null || true
"$IPTABLES" -X "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -X "$CHAIN" 2>/dev/null || true
"$IPTABLES" -t nat -D POSTROUTING -s "$NET" -j MASQUERADE 2>/dev/null || true
"$IP" link del "$VETH_HOST" 2>/dev/null || true
"$IP" netns del "$NETNS_NAME" 2>/dev/null || true

# Resolve the actual default-route interface and reject an ambiguous topology.
mapfile -t routes < <("$IP" -o -4 route show default)
(( ${#routes[@]} == 1 )) || fail "expected exactly one IPv4 default route"
uplink="${routes[0]#* dev }"
uplink="${uplink%% *}"
[[ -n "$uplink" && "$uplink" != "dev" && "$uplink" != "via" ]] || fail "could not parse default-route interface"
"$IP" link show dev "$uplink" >/dev/null || fail "default-route interface is unavailable"

# Record pre-state BEFORE any mutation
old_ip_forward="$("$SYSCTL" -n net.ipv4.ip_forward)"

# Create network objects
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

# Enable ip_forward and record that we changed it
"$SYSCTL" -w net.ipv4.ip_forward=1 >/dev/null
changed_ip_forward=1

# Dedicated IPv4 chain: scoped to fb-sandbox0, non-sandbox traffic returns
"$IPTABLES" -N "$CHAIN"
# Ownership marker
"$IPTABLES" -A "$CHAIN" -m comment --comment "fieldbook-sandbox-ownership-marker"
# Non-sandbox traffic: return immediately
"$IPTABLES" -A "$CHAIN" ! -i "$VETH_HOST" ! -o "$VETH_HOST" -j RETURN
# Host-gateway exposure deny: prevent veth ingress to host-local services
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -d "$HOST_IP" -j DROP
# Allow proxy flow (NEW and ESTABLISHED)
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
# Deny all other egress from sandbox
"$IPTABLES" -A "$CHAIN" -i "$VETH_HOST" -o "$uplink" -s "$NET" -j DROP
# Allow established return traffic to sandbox
"$IPTABLES" -A "$CHAIN" -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
# Terminal drop for remaining sandbox packets
"$IPTABLES" -A "$CHAIN" -j DROP

# Insert jump at earliest position to prevent bypass; record displaced rule
displaced_rule="$("$IPTABLES" -S FORWARD 2>/dev/null | head -1)"
if [[ "$displaced_rule" =~ ^-A\ FORWARD ]]; then
  # Convert -A to -I for restoration
  displaced_rule="-I FORWARD 1 ${displaced_rule#-A FORWARD }"
  "$IPTABLES" -I FORWARD 1 -j "$CHAIN"
else
  # No existing rule or format unexpected
  displaced_rule=""
  "$IPTABLES" -I FORWARD 1 -j "$CHAIN"
fi

# Dedicated IPv6 chain: block all traffic through sandbox veth
"$IP6TABLES" -N "$CHAIN"
"$IP6TABLES" -A "$CHAIN" -m comment --comment "fieldbook-sandbox-ownership-marker"
"$IP6TABLES" -A "$CHAIN" ! -i "$VETH_HOST" ! -o "$VETH_HOST" -j RETURN
"$IP6TABLES" -A "$CHAIN" -i "$VETH_HOST" -j DROP
"$IP6TABLES" -A "$CHAIN" -o "$VETH_HOST" -j DROP
"$IP6TABLES" -A "$CHAIN" -j DROP
"$IP6TABLES" -I FORWARD 1 -j "$CHAIN"

# NAT: not route-dependent; matches source network only
"$IPTABLES" -t nat -A POSTROUTING -s "$NET" -j MASQUERADE
rules_installed=1

# Write runtime state file (root-owned)
cat > "$STATE_FILE" <<EOF
# Fieldbook sandbox runtime state (DO NOT EDIT)
changed_ip_forward=$changed_ip_forward
old_ip_forward=$old_ip_forward
EOF
chown "$STATE_OWNER" "$STATE_FILE"
chmod 600 "$STATE_FILE"

# Verify exact policy, route, readiness, and a blocked alternate destination.
"$IP" -n "$NETNS_NAME" route get "$PROXY_HOST" | grep -Eq "dev $VETH_NS"
"$IPTABLES" -S "$CHAIN" | grep -F -- "-d $PROXY_HOST -p tcp --dport $PROXY_PORT" >/dev/null
"$IPTABLES" -S "$CHAIN" | grep -F -- "-i $VETH_HOST -o $uplink" >/dev/null
"$IPTABLES" -S "$CHAIN" | grep -F -- "-d $HOST_IP" >/dev/null || fail "host-gateway deny rule missing"
"$IPTABLES" -S FORWARD | head -1 | grep -q -- "-j $CHAIN" || fail "FORWARD jump not at earliest position"
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