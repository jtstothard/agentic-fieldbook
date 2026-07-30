#!/bin/bash
# Teardown script for Fieldbook sandbox network namespace

set -e

NETNS_NAME="fieldbook-sandbox"
VETH_HOST="fb-sandbox0"
VETH_NS="fb-sandbox1"
HOST_IP="10.200.2.1"
PROXY_HOST="192.168.10.252"
PROXY_PORT="8318"

# Detect if running as root (no need for sudo)
SUDO=""
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
fi

echo "Tearing down Fieldbook sandbox network namespace: $NETNS_NAME"

# Remove iptables rules
$SUDO iptables -D FORWARD -i "$VETH_HOST" -o eth0 -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -j ACCEPT 2>/dev/null || true
$SUDO iptables -D FORWARD -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
$SUDO iptables -D FORWARD -i "$VETH_HOST" -o eth0 -s "10.200.2.0/24" -j REJECT 2>/dev/null || true
$SUDO iptables -t nat -D POSTROUTING -s "10.200.2.0/24" -j MASQUERADE 2>/dev/null || true

# Delete veth pair
if ip link show "$VETH_HOST" &>/dev/null; then
    $SUDO ip link delete "$VETH_HOST"
fi

# Delete netns
if $SUDO ip netns list | grep -q "^${NETNS_NAME}$"; then
    $SUDO ip netns delete "$NETNS_NAME"
fi

echo "Teardown complete"