"""Runtime invariants for capability-approval contracts."""

import argparse
from pathlib import Path

from agentic_fieldbook.contract import check_capability_approval, validate_capability_approval
from agentic_fieldbook.plugin import _handle_aos_command, _register_aos_cli


VALID = {
    "broker_type": "vault",
    "broker_endpoint": "https://broker.example.test",
    "lease_ttl": 300,
    "operation_limit": 1,
    "contract_digest": "sha256:abc",
    "verification_method": "direct-query",
    "target_immutable": True,
    "approval_channel": "telegram",
    "approval_binding": "contract_digest + target + capability + parameters",
}


def test_valid_capability_approval_contract_is_accepted():
    assert validate_capability_approval(VALID) == []


def test_mutable_target_is_rejected_deterministically():
    errors = validate_capability_approval({**VALID, "target_immutable": False})
    assert errors == ["target_immutable must be true for capability-approval contracts"]


def test_missing_immutable_target_is_rejected_deterministically():
    errors = validate_capability_approval({k: v for k, v in VALID.items() if k != "target_immutable"})
    assert errors == ["missing required field: target_immutable"]


def test_zero_operation_limit_is_rejected():
    assert validate_capability_approval({**VALID, "operation_limit": 0}) == [
        "operation_limit must be an integer >= 1"
    ]


def test_missing_required_fields_are_named():
    errors = validate_capability_approval({})
    assert errors == [f"missing required field: {field}" for field in (
        "broker_type", "broker_endpoint", "lease_ttl", "operation_limit",
        "contract_digest", "verification_method", "target_immutable",
        "approval_channel", "approval_binding",
    )]


def test_contract_command_exposes_runtime_validation(tmp_path: Path, capsys):
    path = tmp_path / "contract.yaml"
    path.write_text("target_immutable: false\noperation_limit: 0\n")
    assert check_capability_approval(str(path)) == 1
    output = capsys.readouterr().err
    assert "target_immutable must be true" in output
    assert "operation_limit must be an integer >= 1" in output


def _parse_public_aos_contract(path: Path) -> argparse.Namespace:
    """Build and parse the same public ``aos contract`` CLI path Hermes uses."""
    parser = argparse.ArgumentParser()
    _register_aos_cli(parser)
    return parser.parse_args(["contract", "--capability-approval", str(path)])


def test_public_cli_accepts_valid_capability_approval_contract(tmp_path: Path, capsys):
    path = tmp_path / "valid.yaml"
    path.write_text("\n".join(f"{key}: {str(value).lower() if isinstance(value, bool) else value}" for key, value in VALID.items()))
    args = _parse_public_aos_contract(path)
    assert args.aos_subcommand == "contract"
    assert _handle_aos_command(args) == 0
    assert "Capability-approval contract valid" in capsys.readouterr().out


def test_public_cli_rejects_mutable_target_and_missing_required_fields(tmp_path: Path, capsys):
    path = tmp_path / "invalid.yaml"
    path.write_text("target_immutable: false\noperation_limit: 0\n")
    args = _parse_public_aos_contract(path)
    assert _handle_aos_command(args) == 1
    output = capsys.readouterr().err
    assert "target_immutable must be true" in output
    assert "operation_limit must be an integer >= 1" in output
    assert "missing required field: broker_type" in output
