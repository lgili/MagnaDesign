# Direct FEA Backend — Engineering Documentation

This directory documents the in-tree FEA backend at
`src/pfc_inductor/fea/direct/`. It exists so a new contributor — human
or AI — can read the math, understand the design choices, and modify
the code without re-deriving everything from scratch.

The documentation is layered: **architecture → physics → parity →
validation → extension**. Read it in the order below the first time;
later, treat it as a reference indexed by topic.

## Reading order

| # | File | What you learn |
|---|---|---|
| 01 | [`01-architecture.md`](01-architecture.md) | Why the direct backend exists, dispatch logic, module map |
| 02 | [`02-reluctance-model.md`](02-reluctance-model.md) | `L = N²/R` analytical solver — the workhorse |
| 03 | [`03-fringing-roters.md`](03-fringing-roters.md) | Roters fringing factor + iterative gap sizing |
| 04 | [`04-toroidal-solver.md`](04-toroidal-solver.md) | Closed-form `B_φ` for wound toroids |
| 05 | [`05-saturation-rolloff.md`](05-saturation-rolloff.md) | `μ_eff(H)` for powder, ferrite, Si-Fe |
| 06 | [`06-dowell-ac-resistance.md`](06-dowell-ac-resistance.md) | Skin + proximity, Litz, foil |
| 07 | [`07-thermal-coupling.md`](07-thermal-coupling.md) | Lumped convection + EM-thermal iteration |
| 08 | [`08-engine-vs-direct-parity.md`](08-engine-vs-direct-parity.md) | Two paths, one physics — invariants + bug history |
| 09 | [`09-validation-benchmarks.md`](09-validation-benchmarks.md) | Numbers: catalog `A_L`, FEMMT, parity sweeps |
| 10 | [`10-known-limitations.md`](10-known-limitations.md) | What we know is wrong + when to escalate |
| 11 | [`11-extending-the-backend.md`](11-extending-the-backend.md) | How to add a shape, material, or physics |
| 12 | [`12-fem-templates-research.md`](12-fem-templates-research.md) | GetDP templates (axi, planar, 3-D, AC) — research path |

## Quick navigation by task

**"I just want to use the backend."** → `01-architecture.md` §2 (public
API) + the parent `README.md`.

**"I'm debugging an `L_FEA` that disagrees with my hand calculation."**
→ `08-engine-vs-direct-parity.md` §3 (invariants) then `09-validation-benchmarks.md`
to compare against the regression sweeps.

**"I need to add a new core shape."** → `11-extending-the-backend.md` §2.

**"How accurate is this?"** → `09-validation-benchmarks.md` — has the
numbers vs catalog data, FEMMT, and engine-vs-direct parity.

**"Something is silently wrong."** → `10-known-limitations.md`. The
LP-powder catalog anomaly, Roters extrapolation regime, and toroid
discrete-gap caveat are documented there.

## Documentation conventions

- **Status badges** at the top of each file: `LIVE` (used in production),
  `RESEARCH` (wired but experimental), `FUTURE` (stub).
- **Code pointers** are `path/to/file.py:LINE` so they survive renames
  better than function names alone. Re-pin them when refactoring.
- **Math** uses inline LaTeX-style notation rendered as code fences.
  GitHub doesn't render LaTeX in regular markdown, so we keep formulas
  legible as plain text:

  ```
  L = μ₀ · N² · A_e / (l_e/μ_r + l_gap/k_fringe)
  ```

- **Variables** are defined once per file under a "Symbols" section
  near the top, then reused. No new symbol gets introduced without a
  definition.
- **Validation numbers** carry a date stamp + benchmark script. If a
  number drifts, the script in `scripts/` is the source of truth.

## Where this documentation does NOT live

- `openspec/specs/fea-direct-backend/spec.md` — formal requirements
  (GIVEN/WHEN/THEN scenarios). That's the contract; this directory is
  the implementation rationale.
- `docs/FEA.md` — user-facing migration guide for the FEMMT → direct
  cutover. End-user documentation, not engineering.
- `docs/theory/*.rst` — analytical-engine physics (Dowell, Steinmetz,
  rolloff) for the **non-FEA** path. The direct backend reuses those
  modules; this directory describes the FEA-side glue.

## When to update this directory

Anytime you:

1. Change physics (new equation, different fringing model, different
   thermal closure).
2. Change the public API of `runner.py` or `models.py`.
3. Fix a bug whose root cause is "engine and direct disagreed" (update
   `08-engine-vs-direct-parity.md` with the new invariant + test).
4. Add a new module under `physics/`, `geometry/`, or extend the
   shape coverage.

The corresponding regression test in `tests/` is the single source of
truth for the invariant. The doc explains the *why*; the test enforces
the *what*.
