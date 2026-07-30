#!/bin/bash
# Source for the installed Fieldbook sandbox teardown runtime.
set -Eeuo pipefail
readonly IP=/usr/sbin/ip
readonly IPTABLES=/usr/sbin/iptables
readonly IP6TABLES=/usr/sbin/ip6tables
readonly NETNS_NAME=fieldbook-sandbox
readonly VETH_HOST=fb-sandbox0
readonly CHAIN=FIELDBOOK_SANDBOX
readonly NET=10.200.2.0/24

(( EUID == 0 )) || { printf 'must run as root\n' >&2; exit 1; }
# Delete only the dedicated chain and objects owned by this sandbox.
"$IPTABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
mapfile -t routes < <("$IP" -o -4 route show default)
if (( ${#routes[@]} == 1 )); then
  uplink="${routes[0]#* dev }"
  uplink="${uplink%% *}"
  "$IPTABLES" -t nat -D POSTROUTING -s "$NET" -o "$uplink" -j MASQUERADE 2>/dev/null || true
fi
"$IPTABLES" -F "$CHAIN" 2>/dev/null || true
"$IPTABLES" -X "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -D FORWARD -j "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -F "$CHAIN" 2>/dev/null || true
"$IP6TABLES" -X "$CHAIN" 2>/dev/null || true
"$IP" link del "$VETH_HOST" 2>/dev/null || true
"$IP" netns del "$NETNS_NAME" 2>/dev/null || true
printf 'Fieldbook sandbox teardown complete\n'
