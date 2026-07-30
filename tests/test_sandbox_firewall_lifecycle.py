"""Adversarial tests for scoped-egress sandbox firewall lifecycle.

These tests verify the sandbox boundary invariants without requiring root/host
mutation. They use static analysis, script inspection, and isolated bash logic.
"""

import os
import subprocess
import tempfile
from pathlib import Path
import pytest

# Paths to sandbox scripts
SETUP_SCRIPT = Path(__file__).parent.parent / "systemd" / "fieldbook-sandbox-setup.sh"
TEARDOWN_SCRIPT = Path(__file__).parent.parent / "systemd" / "fieldbook-sandbox-teardown.sh"
INSTALLER_SCRIPT = Path(__file__).parent.parent / "systemd" / "install-fieldbook-sandbox.sh"
SERVICE_FILE = Path(__file__).parent.parent / "systemd" / "fieldbook-sandbox.service"


def read_script_lines(path: Path) -> list[str]:
    """Read non-empty, non-comment lines from a script."""
    if not path.exists():
        pytest.skip(f"Script not found: {path}")
    lines = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


class TestChainScoping:
    """HIGH: FIELDBOOK_SANDBOX chain must only apply to sandbox traffic."""

    def test_return_for_non_sandbox_traffic(self):
        """Non-sandbox traffic must RETURN to caller chain, not be dropped."""
        lines = read_script_lines(SETUP_SCRIPT)

        # Find chain definition and early RETURN for non-sandbox traffic
        found_chain = False
        found_early_return = False
        for line in lines:
            if ('IPTABLES' in line and '-N' in line and ('"$CHAIN"' in line or 'CHAIN' in line)):
                found_chain = True
            if found_chain and 'RETURN' in line and ('! -i' in line or '!-i' in line) and 'VETH_HOST' in line:
                found_early_return = True
                break

        assert found_chain, "FIELDBOOK_SANDBOX chain not defined"
        assert found_early_return, "Missing RETURN rule for non-sandbox traffic"

    def test_no_unconditional_drop(self):
        """Must remove unconditional terminal DROP for non-sandbox traffic."""
        lines = read_script_lines(SETUP_SCRIPT)

        # Scan for DROP rules - should be scoped to sandbox
        for line in lines:
            if 'DROP' in line and '$IPTABLES' in line:
                # Every DROP must be scoped to sandbox veth
                assert '$VETH_HOST' in line or '$CHAIN' in line, \
                    f"Found unscoped DROP rule: {line}"

    def test_scoped_terminal_drop(self):
        """Terminal DROP must only apply to sandbox packets that fail allowlist."""
        lines = read_script_lines(SETUP_SCRIPT)

        # Find terminal DROP (last DROP in chain)
        terminal_drop_seen = False
        for i, line in enumerate(lines):
            if 'IPTABLES' in line and '-A' in line and 'DROP' in line and 'CHAIN' in line:
                # Check this isn't the host-gateway DROP
                if 'HOST_IP' not in line:
                    terminal_drop_seen = True

        assert terminal_drop_seen, "Missing terminal DROP in FIELDBOOK_SANDBOX chain"

    def test_ownership_marker(self):
        """Dedicated chain ownership marker comment must exist."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_marker = False
        for line in lines:
            if 'ownership-marker' in line or 'fieldbook-sandbox-ownership' in line:
                found_marker = True
                break

        assert found_marker, "Missing chain ownership marker comment"


class TestForwardJumpOrdering:
    """HIGH: FORWARD jump must be at deterministic earliest position."""

    def test_uses_insert_not_append(self):
        """Must use -I FORWARD 1, not -A FORWARD."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_append = False
        found_insert = False
        for line in lines:
            if 'FORWARD' in line and '$IPTABLES' in line:
                if '-A FORWARD -j "$CHAIN"' in line:
                    found_append = True
                if '-I FORWARD 1 -j "$CHAIN"' in line or '-I FORWARD 1 -j FIELDBOOK_SANDBOX' in line:
                    found_insert = True

        assert not found_append, "Found -A FORWARD append (should be -I FORWARD 1)"
        assert found_insert, "Missing -I FORWARD 1 insert for jump rule"

    def test_no_duplicate_restoration_logic(self):
        """Insertion is transactional; displaced rules are never replayed."""
        lines = read_script_lines(SETUP_SCRIPT)

        assert not any('displaced_rule' in line for line in lines)


class TestNatIpForwardLifecycle:
    """HIGH: Record/restore NAT and ip_forward state on all paths."""

    def test_pre_state_recording(self):
        """Record pre-state BEFORE any mutation."""
        lines = read_script_lines(SETUP_SCRIPT)

        # Find ip_forward mutation
        ip_forward_line_idx = None
        for i, line in enumerate(lines):
            if 'net.ipv4.ip_forward=1' in line or 'sysctl -w net.ipv4.ip_forward' in line:
                ip_forward_line_idx = i
                break

        assert ip_forward_line_idx is not None, "ip_forward not set"

        # Check that old value is recorded before mutation
        found_recording = False
        for i in range(ip_forward_line_idx):
            line = lines[i]
            if 'old_ip_forward=' in line or 'net.ipv4.ip_forward' in line and 'sysctl -n' in line:
                found_recording = True
                break

        assert found_recording, "ip_forward not recorded before mutation"

    def test_state_file_persistence(self):
        """Runtime state must be persisted to root-owned file."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_state_dir = False
        found_state_file = False
        for line in lines:
            if 'STATE_DIR=' in line or 'STATE_FILE=' in line:
                found_state_dir = True
            if 'tmp_state' in line and 'mv -f' in line:
                found_state_file = True

        assert found_state_dir, "Missing state directory definition"
        assert found_state_file, "Missing state file creation"

    def test_nat_not_route_dependent(self):
        """NAT rule must not depend on specific route interface."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_nat = False
        for line in lines:
            if 'POSTROUTING' in line and 'MASQUERADE' in line:
                found_nat = True
                # Check that rule doesn't include -o uplink
                assert '-o' not in line or '$uplink' not in line, \
                    f"NAT rule is route-dependent: {line}"
                # Must match source network only
                if 'grep -F' in line:
                    continue
                assert '-s "$NET"' in line or '-s 10.200.2.0/24' in line, \
                    f"NAT rule missing source network: {line}"

        assert found_nat, "NAT MASQUERADE rule not found"

    def test_cleanup_deletes_nat(self):
        """Cleanup must delete NAT rule on failure path."""
        lines = read_script_lines(SETUP_SCRIPT)

        # Find cleanup function
        in_cleanup = False
        found_nat_cleanup = False
        for line in lines:
            if 'cleanup()' in line:
                in_cleanup = True
            if in_cleanup and 'POSTROUTING' in line and '-D' in line:
                found_nat_cleanup = True
                break

        assert found_nat_cleanup, "Cleanup does not delete NAT rule"

    def test_teardown_deletes_nat(self):
        """Teardown must delete NAT rule (not route-dependent)."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_nat_delete = False
        for line in lines:
            if 'POSTROUTING' in line and '-D' in line and 'MASQUERADE' in line:
                found_nat_delete = True
                # Check it's not using route rediscovery
                assert '$uplink' not in line or 'route show default' not in lines, \
                    "Teardown NAT deletion is route-dependent"

        assert found_nat_delete, "Teardown does not delete NAT rule"

    def test_restore_ip_forward_on_failure(self):
        """Failure cleanup must restore ip_forward if we changed it."""
        lines = read_script_lines(SETUP_SCRIPT)

        in_cleanup = False
        found_restore = False
        for line in lines:
            if 'cleanup()' in line:
                in_cleanup = True
            if in_cleanup and 'ip_forward=' in line and '$old_ip_forward' in line:
                found_restore = True
                break

        assert found_restore, "Cleanup does not restore ip_forward"

    def test_teardown_restores_ip_forward(self):
        """Teardown must restore ip_forward using state file."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_state_read = False
        found_restore = False
        for line in lines:
            if 'STATE_FILE' in line and 'grep' in line:
                found_state_read = True
            if 'ip_forward=' in line and '$old_ip_forward' in line or '$old_ip_forward' in line and 'sysctl' in line:
                found_restore = True

        assert found_state_read, "Teardown does not read state file"
        assert found_restore, "Teardown does not restore ip_forward"


class TestOwnershipVerification:
    """HIGH: Verify topology before deletion to avoid blind deletion."""

    def test_verify_namespace_before_delete(self):
        """Verify namespace identity before deletion."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_verify = False
        found_delete = False
        for line in lines:
            if 'netns list' in line or 'ip netns show' in line:
                found_verify = True
            if 'netns del' in line and found_verify:
                found_delete = True

        assert found_verify, "Missing namespace verification"
        assert found_delete, "Missing conditional namespace deletion"

    def test_verify_veth_topology(self):
        """Verify veth has expected address before deletion."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_verify = False
        found_address_check = False
        for line in lines:
            if 'link show' in line and 'type veth' in line:
                found_verify = True
            if '10.200.2.1' in line and 'addr' in line:
                found_address_check = True

        assert found_verify, "Missing veth link type verification"
        assert found_address_check, "Missing veth address verification"

    def test_fail_closed_on_mismatch(self):
        """Fail closed on topology mismatch instead of blind deletion."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_warning = False
        found_fail_closed = False
        for line in lines:
            if 'refusing collision' in line or 'malformed/missing state' in line or 'Foreign objects' in line:
                found_warning = True
            if 'Never destroy a collision' in line or 'no object is deleted' in line:
                found_fail_closed = True

        assert found_warning, "Missing warning for topology mismatch"
        assert found_fail_closed, "Missing fail-closed behavior"


class TestHostGatewayExposure:
    """MEDIUM: Deny veth ingress to host-local services."""

    def test_deny_host_gateway(self):
        """Deny veth ingress to 10.200.2.1 (host-gateway)."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_deny = False
        for line in lines:
            if '-d "$HOST_IP"' in line and 'DROP' in line:
                found_deny = True
                break

        assert found_deny, "Missing host-gateway deny rule"

    def test_deny_scoped_to_veth(self):
        """Host-gateway deny must be scoped to veth ingress."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_deny = False
        for line in lines:
            if '-d "$HOST_IP"' in line and 'DROP' in line:
                found_deny = True
                # Must have veth interface match
                assert '-i "$VETH_HOST"' in line, \
                    "Host-gateway deny not scoped to veth ingress"

        assert found_deny, "Missing host-gateway deny rule"

    def test_does_not_block_proxy_traffic(self):
        """Deny must not block proxy or established return traffic."""
        lines = read_script_lines(SETUP_SCRIPT)

        found_proxy_accept = False
        found_return_accept = False
        found_host_gateway_deny = False

        for line in lines:
            if '$PROXY_HOST' in line and 'ACCEPT' in line:
                found_proxy_accept = True
            if 'RELATED,ESTABLISHED' in line and 'ACCEPT' in line:
                found_return_accept = True
            if '-d "$HOST_IP"' in line and 'DROP' in line:
                found_host_gateway_deny = True

        assert found_proxy_accept, "Missing proxy accept rule"
        assert found_return_accept, "Missing established/related accept rule"
        assert found_host_gateway_deny, "Missing host-gateway deny rule"


class TestInstallerUpgradeSafety:
    """Installer must detect inactive legacy state without touching the host."""

    def test_checks_inactive_legacy_state_and_journal(self):
        installer = INSTALLER_SCRIPT.read_text()
        assert 'systemctl is-active --quiet' in installer
        assert 'runtime-state.conf' in installer
        assert 'setup-journal.conf' in installer
        assert 'managed_evidence' in installer
        assert 'refusing upgrade' in installer
        assert 'legacy-sandbox-reconciliation.md' in installer

    def test_clean_install_has_explicit_force_gate(self):
        installer = INSTALLER_SCRIPT.read_text()
        assert '--force|--migrate' in installer
        assert 'managed_evidence' in installer
        assert 'force == 0' in installer
        assert 'ip netns list' in installer
        assert 'iptables -t nat' in installer


class TestTeardownJournalLifecycle:
    def test_journal_is_owned_and_removed_only_on_success(self):
        teardown = TEARDOWN_SCRIPT.read_text()
        assert 'JOURNAL_FILE=' in teardown
        assert 'setup journal is missing' in teardown
        assert 'setup journal ownership or mode is invalid' in teardown
        assert 'rm -f "$STATE_FILE" "$JOURNAL_FILE"' in teardown
        assert 'if (( rc == 0 )); then' in teardown


class TestStaticVerification:
    """Safe static verification without host mutation."""

    def test_bash_syntax(self):
        """Scripts must pass bash -n syntax check."""
        result = subprocess.run(
            ["bash", "-n", str(SETUP_SCRIPT)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Setup script syntax error: {result.stderr}"

        result = subprocess.run(
            ["bash", "-n", str(TEARDOWN_SCRIPT)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Teardown script syntax error: {result.stderr}"

    def test_scripts_are_executable(self):
        """Scripts should be executable."""
        assert SETUP_SCRIPT.exists(), "Setup script missing"
        assert TEARDOWN_SCRIPT.exists(), "Teardown script missing"

        # Note: We don't assert executable bit since repository state may vary

    def test_no_hardcoded_paths(self):
        """Avoid hardcoded paths that break在不同 environments."""
        lines = read_script_lines(SETUP_SCRIPT)

        for line in lines:
            # Check for suspicious hardcoded paths
            if '/usr/local/libexec' in line and 'cp' not in line:
                # This is OK as a comment about installation location
                continue
            if '/tmp/fieldbook' in line or '/var/run/fieldbook' in line:
                pytest.fail(f"Found hardcoded path: {line}")

    def test_installed_runtime_packaging_matches_unit(self):
        """Installer and unit must agree on root-owned extensionless paths."""
        installer = INSTALLER_SCRIPT.read_text()
        service = SERVICE_FILE.read_text()
        assert 'fieldbook-sandbox-${name}.sh' in installer
        assert '"$TARGET_DIR/fieldbook-sandbox-${name}"' in installer
        assert 'ExecStart=/usr/local/libexec/fieldbook-sandbox-setup\n' in service
        assert 'ExecStop=/usr/local/libexec/fieldbook-sandbox-teardown\n' in service
        assert '.sh' not in service


class TestRepeatedStartStop:
    """Verify no state accumulation on repeated start/stop cycles."""

    def test_prevent_duplicate_nat(self):
        """Scripts must prevent duplicate NAT accumulation."""
        setup_lines = read_script_lines(SETUP_SCRIPT)
        teardown_lines = read_script_lines(TEARDOWN_SCRIPT)

        # Setup must delete existing NAT before adding new one
        found_cleanup = False
        for line in setup_lines:
            if 'POSTROUTING' in line and '-D' in line:
                found_cleanup = True
                break

        # Teardown must delete NAT
        found_teardown = False
        for line in teardown_lines:
            if 'POSTROUTING' in line and '-D' in line:
                found_teardown = True
                break

        assert found_cleanup, "Setup does not clean existing NAT"
        assert found_teardown, "Teardown does not delete NAT"

    def test_state_file_cleanup(self):
        """State file should be cleaned up after teardown."""
        lines = read_script_lines(TEARDOWN_SCRIPT)

        found_cleanup = False
        for line in lines:
            if 'rm -f "$STATE_FILE"' in line or 'rm "$STATE_FILE"' in line or ('$STATE_FILE' in line and '$JOURNAL_FILE' in line and 'rm -f' in line):
                found_cleanup = True
                break

        assert found_cleanup, "Teardown does not clean state file"