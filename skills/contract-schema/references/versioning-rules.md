# Contract Versioning Rules

## Core principle

The contract core (objective, scope, risk, capabilities, acceptance criteria, evidence requirements) is **immutable** once work begins. Material changes create a new revision. Minor corrections stay in revision.

## When to bump revision

**Bump revision (material change):**
- Changing objective or success_definition
- Modifying scope (adding or removing in_scope items or exclusions)
- Reassessing risk class (changing low→medium→high or vice versa)
- Adding or removing capabilities (permitted_tools, paths, hosts, accounts, side_effects)
- Adding or removing acceptance criteria (required list changes)
- Adding or removing evidence requirements
- Role reassignment (different executor, verifier, or approver)

**No bump (minor correction):**
- Typo fixes in comments or descriptions
- Path corrections within existing scope
- Equivalent command swaps (e.g. `pytest` → `python -m pytest`)
- Correcting formatting or presentation
- Updating timestamps or metadata

## Revision numbering

- Start at revision 1.
- Increment by 1 for each material change.
- Gaps are allowed (e.g., skip from 3→5 for clarity).
- The revision history is recorded in `lifecycle.history`.

## Supersession

When a revision is created:
1. The previous contract state is set to `superseded`.
2. The new revision becomes the active contract.
3. `lifecycle.history` records the supersedence transition with the reason.
4. Work in progress on the previous revision is assessed for compatibility.

## Stages are append-only

Each stage (planning, execution, review, verification) appends to the contract history. Stages never rewrite prior stage records. If a stage must be re-run, a new entry is appended with a fresh timestamp and actor.

## Evidence records are immutable

Once an `evidence_record` is written to a stage output envelope, it cannot be modified. Corrections or updates create new records with a clear reference to the original.