# Agentic Fieldbook setup

## v0.1 Installation (Plugin stub)

### Quick install

The v0.1 plugin stub is installable via the Hermes plugin mechanism from the public repository:

```bash
hermes plugins install git+https://github.com/jtstothard/agentic-fieldbook.git
```

This registers the `hermes aos` namespace with stub subcommands (`setup`, `doctor`, `version`).

### Verify installation

```bash
hermes aos version
# Expected: Agentic Fieldbook v0.1.0
#          Hermes compatibility: >=0.18.0

hermes aos setup
# Expected: Agentic Fieldbook v0.1.0 setup — stub

hermes aos doctor
# Expected: Agentic Fieldbook v0.1.0 doctor — stub
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

### v0.1 scope

This stub provides:

- Plugin metadata and registration
- `hermes aos setup` — stub (interactive setup coming in later tickets)
- `hermes aos doctor` — stub (runtime verification coming in later tickets)
- `hermes aos version` — reports bundle version and Hermes compatibility

Full functionality (skills, calibration artifacts, runtime verification) will be added incrementally in following tickets.

---

## Further notes

- The plugin is userland: it adds CLI commands but does not load skills in v0.1.
- Skills tap registration and lane-calibration skill are planned for later tickets after Hermes plugin API confirmations.
- BUILD-SPEC.md documents the full v0.1 design; this stub enables incremental delivery.

For more details, see:
- BUILD-SPEC.md
- https://github.com/jtstothard/agentic-fieldbook