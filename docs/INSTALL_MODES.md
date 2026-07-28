# Install Modes

Agentic Fieldbook v0.2.0 supports two installation modes: `--minimal` and `--starter`.

## Minimal Mode (`--minimal`)

The minimal mode provides a v0.1-equivalent installation with no starter-kit features:

```bash
hermes aos setup --minimal --yes
```

**What you get:**
- Core Agentic Fieldbook skills
- Basic setup and doctor commands
- SOUL.md integration
- No profile templates
- No first-pilot flow

**When to use:**
- Upgrading from v0.1.0 and want to keep things simple
- You already have a working Hermes profile setup
- You want to add starter-kit features later

## Starter Mode (`--starter`)

The starter mode installs the v0.2.0 starter-kit:

```bash
hermes aos setup --starter --yes
```

**What you get:**
- Everything in minimal mode
- Profile templates for canonical AOS roles (planner, executor, reviewer, verifier)
- Guided first-pilot flow for collecting calibration data
- Full interactive `hermes aos map-lanes` wizard

**When to use:**
- Fresh installation
- You want to try the full v0.2.0 experience
- You need help setting up AOS lane profiles

## Upgrade Path from v0.1.0

### Automatic Detection

When you run `hermes aos setup` on a v0.1.0 installation, the plugin detects the upgrade and:

1. **Defaults to minimal mode** - Preserves your existing v0.1.0 setup
2. **Prompts about starter layer** - Informs you about the available starter-kit features
3. **Provides upgrade command** - Shows how to add the starter-kit later

### Manual Upgrade from Minimal to Starter

If you installed in minimal mode (either explicitly or via v0.1.0 upgrade), you can add the starter-kit at any time:

```bash
hermes aos setup --starter --yes
```

This will:
- Detect your existing minimal installation
- Add the starter-kit features (templates, first-pilot flow)
- Preserve your existing SOUL.md configuration

## Flags are Mutually Exclusive

The `--minimal` and `--starter` flags are mutually exclusive. You cannot specify both at the same time.

If you try to use both flags, the setup command will fail with an error:

```
ERROR: Cannot specify both --minimal and --starter
```

## Default Behavior

If you run `hermes aos setup` without specifying `--minimal` or `--starter`:

- **Fresh installation**: Defaults to `--minimal` mode
- **v0.1.0 upgrade**: Automatically detects v0.1.0 and defaults to `--minimal` mode with a prompt

## Verifying Your Install Mode

You can check your current install mode by looking at the marker file:

```bash
cat ~/.hermes/plugins/agentic-fieldbook/install-mode.txt
```

This will show either `minimal` or `starter`.

## Install Mode Persistence

Your install mode choice is persisted in:
- `~/.hermes/plugins/agentic-fieldbook/install-mode.txt`

This marker file is used for:
- Detecting v0.1.0 upgrades (no marker file but SOUL.md exists)
- Tracking your installation mode for future operations
- Enabling conditional behavior in the `doctor` command (T08)

## Recommendations

### For New Users

Start with `--starter` mode if you're new to Agentic Fieldbook:

```bash
hermes aos setup --starter --yes
```

Then run the profile mapping wizard:

```bash
hermes aos map-lanes
```

### For v0.1.0 Users

Stay in minimal mode if everything is working:

```bash
hermes aos setup --yes
```

Try the starter-kit later if you're curious:

```bash
hermes aos setup --starter --yes
```