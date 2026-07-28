# 02 — Build `hermes aos map-lanes` wizard + binding persistence

**What to build:** A separate, re-runnable command that walks the user through binding their Hermes profiles to the four AOS roles (planner, executor, reviewer, verifier). Persists the result in a generated config file. Integrates binding validation into `doctor`. This is the wizard deferred from v0.1 ticket 01 — it makes the roles-first abstraction concretely bindable to a real estate.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `hermes aos map-lanes` command registered and runnable
- [ ] `hermes aos setup` prints a pointer to `map-lanes` as the next step after activation
- [ ] Wizard offers three paths per role: map-existing profile, build-from-template (consumes ticket 05 templates when available; gracefully notes "templates not installed" if absent), skip
- [ ] Crossover allowed: one profile bindable to multiple AOS roles
- [ ] A skipped role degrades gracefully (method functions with unbound roles; not a failure)
- [ ] Persistence: `~/.hermes/aos-lanes.yaml` written by the wizard (canonical path)
- [ ] Read-on-load: re-running for one role preserves all other existing bindings unchanged
- [ ] `doctor` validates the binding file: schema validity, role coverage, referenced-profile existence
- [ ] `doctor` reports unbound roles as a state, not a failure
- [ ] Direct hand-edits to the binding file are not clobbered by the wizard (documented "you own it now" boundary)
