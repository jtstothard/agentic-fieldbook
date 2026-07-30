import json
import tempfile
from pathlib import Path
from agentic_fieldbook.claude_code_adapter import ClaudeCodeAdapter
from agentic_fieldbook.lifecycle import TaskContract, LifecycleState
from agentic_fieldbook.storage import PortableTaskStore

print('trust_bwrap=', ClaudeCodeAdapter._trusted_bwrap_path())
print('trust_claude=', ClaudeCodeAdapter._trusted_executable_path('claude'))
with tempfile.TemporaryDirectory(prefix='fieldbook-real-') as d:
    root = Path(d)
    (root / 'workspace.txt').write_text('before\n')
    (root / 'home').mkdir()
    # Direct production runner invocation: real trusted Claude executable, real bwrap.
    rc, out, err = ClaudeCodeAdapter._run_process(
        'claude', '--version', cwd=str(root), timeout=30,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(root / 'home'), 'LANG': 'C', 'LC_ALL': 'C'})
    print('direct_rc=', rc)
    print('direct_stdout=', repr(out[:1000]))
    print('direct_stderr=', repr(err[:1000]))
    contract = TaskContract(contract_id='REAL-CLAUDE', objective='probe', scope=('.',), exclusions=(), risk_class='low', capabilities=(), acceptance_criteria=(), required_evidence=('claude-output',), domain='coding.v1')
    store = PortableTaskStore(root / 'store')
    adapter = ClaudeCodeAdapter(contract=contract, store=store, executor_capabilities=(), workspace_root=root, timeout=45)
    result = adapter.dispatch('Reply with a short status only; do not modify files.', assignee='claude-code')
    record = store.load(result.task_id)
    print('dispatch_success=', result.success)
    print('dispatch_reason=', result.metadata.get('reason'))
    print('record_state=', record.state.value)
    print('provenance=', json.dumps(record._provenance, sort_keys=True))
