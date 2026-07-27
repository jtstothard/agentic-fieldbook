# Agentic Fieldbook setup

## v0.1 Installation (Plugin stub)

### Quick install

The v0.1 plugin stub is installable via the Hermes plugin mechanism from the public repository:

```bash
hermes plugins install git+https://github.com/jtstothard/agentic-fieldbook.git
```

This registers the `hermes aos` namespace with stub subcommands (`setup`, `doctor`, `version`, `preflight`).

### Verify installation

```bash
hermes aos version
# Expected: Agentic Fieldbook v0.1.0
#          Hermes compatibility: >=0.18.0

hermes aos setup
# Expected: Agentic Fieldbook v0.1.0 setup — stub

hermes aos doctor
# Expected: Agentic Fieldbook v0.1.0 doctor — stub

hermes aos preflight --profile <profile-name>
# Expected: ✓ All 7 Fieldbook skills available on profile '<profile-name>'
#          or diagnostic listing missing skills
```

### Manual install (alternative)

If automatic plugin installation is unavailable:

```bash
# Clone the repository
git clone https://github.com/jtstothard/agentic-fieldbook.git
cd agentic-fieldbook

# Install as a package in the Hermes environment
# (adjust path to your Hermes venv as needed)
source ~/.hermes/venv/bin/activate  # or your hermes venv
pip install -e .
```

### Profile scoping

Agentic Fieldbook skills are **profile-scoped**, not global. Each Hermes profile maintains its own skill inventory via the plugin mechanism. This means:

- Skills are installed per-profile, not system-wide
- A profile that will receive a kanban card with `--skill <fieldbook-skill>` must have the plugin installed
- The same profile can both issue commands (via the plugin) and receive skill-forced work (via skills)

#### Preflight before dispatch

Before dispatching a kanban card that forces a Fieldbook skill, verify the target profile has all 7 skills installed:

```bash
hermes aos preflight --profile <target-profile>
```

This command:
- Lists installed skills on `<target-profile>` via `hermes --profile <target-profile> skills list`
- Checks for all 7 Fieldbook skills: `contract-schema`, `risk-taxonomy`, `stage-handoff`, `lane-calibration`, `knowledge-lifecycle`, `planning-routing`, `review-calibration`
- Exits 0 if all present, 1 with diagnostic if any are missing

If skills are missing, the diagnostic suggests:
1. Install the plugin on the target profile:
   ```bash
   hermes --profile <target-profile> plugins install git+https://github.com/jtstothard/agentic-fieldbook.git
   ```
2. Or remove the forced skill from the kanban card and copy the method inline instead

#### Alternative: inline method

If you cannot install the plugin on the target profile, omit the `--skill` flag from the kanban card and copy the relevant method from the skill directly into the card body. This avoids the skill dependency entirely.

### v0.1 scope

This stub provides:

- Plugin metadata and registration
- `hermes aos setup` — stub (interactive setup coming in later tickets)
- `hermes aos doctor` — stub (runtime verification coming in later tickets)
- `hermes aos version` — reports bundle version and Hermes compatibility
- `hermes aos preflight` — validates Fieldbook skills on target profiles

Full functionality (skills, calibration artifacts, runtime verification) will be added incrementally in following tickets.

---

## Further notes

- The plugin is userland: it adds CLI commands but does not load skills in v0.1.
- Skills tap registration and lane-calibration skill are planned for later tickets after Hermes plugin API confirmations.
- BUILD-SPEC.md documents the full v0.1 design; this stub enables incremental delivery.

For more details, see:
- BUILD-SPEC.md
- https://github.com/jtstothard/agentic-fieldbook