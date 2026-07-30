#!/bin/bash
# Setup script for Fieldbook sandbox network namespace
# Creates a persistent network namespace with scoped egress to LiteLLM proxy

set -e

NETNS_NAME="fieldbook-sandbox"
VETH_HOST="fb-sandbox0"
VETH_NS="fb-sandbox1"
HOST_IP="10.200.2.1"
NS_IP="10.200.2.2"
HOST_IFACE="eth0"
PROXY_HOST="192.168.10.252"
PROXY_PORT="8318"

# Detect if running as root (no need for sudo)
SUDO=""
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
fi

echo "Setting up Fieldbook sandbox network namespace: $NETNS_NAME"

# Remove existing netns if it exists (for idempotent runs)
if $SUDO ip netns list | grep -q "^${NETNS_NAME}$"; then
    echo "Removing existing netns: $NETNS_NAME"
    $SUDO ip netns delete "$NETNS_NAME"
fi

# Remove existing veth pair if it exists
if ip link show "$VETH_HOST" &>/dev/null; then
    echo "Removing existing veth pair: $VETH_HOST"
    $SUDO ip link delete "$VETH_HOST"
fi

# Create network namespace
$SUDO ip netns add "$NETNS_NAME"

# Create veth pair
$SUDO ip link add "$VETH_HOST" type veth peer name "$VETH_NS"

# Move one end to netns
$SUDO ip link set "$VETH_NS" netns "$NETNS_NAME"

# Configure host side
$SUDO ip addr add "$HOST_IP/24" dev "$VETH_HOST"
$SUDO ip link set "$VETH_HOST" up

# Configure netns side
$SUDO ip netns exec "$NETNS_NAME" ip addr add "$NS_IP/24" dev "$VETH_NS"
$SUDO ip netns exec "$NETNS_NAME" ip link set "$VETH_NS" up
$SUDO ip netns exec "$NETNS_NAME" ip link set lo up

# Set default route in netns via host
$SUDO ip netns exec "$NETNS_NAME" ip route add default via "$HOST_IP"

# Enable IP forwarding on host
$SUDO sysctl -w net.ipv4.ip_forward=1

# Flush any existing rules for our veth to avoid duplicates
$SUDO iptables -D FORWARD -i "$VETH_HOST" -o "$HOST_IFACE" -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -j ACCEPT 2>/dev/null || true
$SUDO iptables -D FORWARD -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
$SUDO iptables -D FORWARD -i "$VETH_HOST" -o "$HOST_IFACE" -s "10.200.2.0/24" -j REJECT 2>/dev/null || true
$SUDO iptables -t nat -D POSTROUTING -s "10.200.2.0/24" -j MASQUERADE 2>/dev/null || true

# Add iptables rules for scoped egress (allow only proxy host:port)
$SUDO iptables -A FORWARD -i "$VETH_HOST" -o "$HOST_IFACE" -d "$PROXY_HOST" -p tcp --dport "$PROXY_PORT" -j ACCEPT
$SUDO iptables -A FORWARD -o "$VETH_HOST" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
# Explicitly reject every other routed destination. This is required even when
# the host FORWARD policy is ACCEPT.
$SUDO iptables -A FORWARD -i "$VETH_HOST" -o "$HOST_IFACE" -s "10.200.2.0/24" -j REJECT

# Add NAT masquerade for outbound traffic
$SUDO iptables -t nat -A POSTROUTING -s "10.200.2.0/24" -j MASQUERADE

# Test connectivity to proxy
echo "Testing connectivity to proxy $PROXY_HOST:$PROXY_PORT..."
if $SUDO ip netns exec "$NETNS_NAME" curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${PROXY_HOST}:${PROXY_PORT}/health/readiness" | grep -q "200"; then
    echo "✓ Proxy connectivity verified"
else
    echo "✗ Proxy connectivity test failed"
    echo "Note: /health/readiness may not exist on all proxy deployments"
    echo "Attempting basic TCP connection test..."
    if $SUDO ip netns exec "$NETNS_NAME" timeout 3 bash -c "</dev/tcp/${PROXY_HOST}/${PROXY_PORT}" 2>/dev/null; then
        echo "✓ TCP connection to proxy succeeded"
    else
        echo "✗ TCP connection to proxy failed"
    fi
fi

# Test that other hosts are blocked
echo "Testing that other hosts are blocked..."
if $SUDO ip netns exec "$NETNS_NAME" timeout 3 curl -s -o /dev/null -w "%{http_code}" "http://example.com:80" 2>/dev/null | grep -v "000\|timed out"; then
    echo "⚠ Warning: Non-proxy host reachable - egress may not be properly scoped"
else
    echo "✓ Non-proxy host blocked as expected"
fi

echo "Setup complete: $NETNS_NAME (veth: $VETH_HOST <-> $VETH_NS, netns IP: $NS_IP)"
echo "Scoped egress: $PROXY_HOST:$PROXY_PORT only"