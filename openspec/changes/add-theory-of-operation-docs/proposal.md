# Add Theory-of-Operation documentation site (Sphinx)

## Why

MagnaDesign's physics models (Steinmetz + iGSE, Dowell, DC-bias
rolloff, anhysteretic B–H, iterative thermal coupling) are
well-implemented in code with paper citations in the docstrings.
But there's no place a user — or, more importantly, a quality
auditor — can read the **end-to-end derivation**: which equation
does the engine use for what, with what assumptions, calibrated
against which data, with what uncertainty.

ISO 9001 / IATF 16949 / IEC 60335 audits ask for "design tool
qualification documentation." Today the answer is "read the source
code", which is not auditable. Industrial users won't push
MagnaDesign past the prototyping phase without a Theory-of-
Operation document they can attach to their design dossier.

The same document doubles as **the onboarding manual** for new
engineers joining the project: a single source explaining "this
is why we use iGSE for non-sinusoidal core loss" lets them
contribute meaningfully on day 5 instead of day 30.

## What changes

A Sphinx-built documentation site published to GitHub Pages,
sourced from `docs/`. Structure:

```
docs/
├── conf.py
├── index.rst
├── getting-started/      ← keeps the current README content
│   ├── install.rst
│   ├── first-design.rst
│   └── tour.rst
├── theory/               ← THE NEW chapter — one page per module
│   ├── overview.rst        — block diagram of the engine
│   ├── steinmetz-igse.rst   — core loss model
│   ├── dowell.rst           — AC copper resistance
│   ├── rolloff.rst          — DC-bias permeability
│   ├── thermal.rst          — iterative thermal coupling
│   ├── anhysteretic-bh.rst  — operating-point B–H trace
│   ├── feasibility.rst      — Tier-0 envelope check
│   └── compliance.rst       — IEC 61000-3-2 derivation
├── topology/             ← per-topology design notes
│   ├── boost-ccm.rst
│   ├── line-reactor.rst
│   └── passive-choke.rst
├── validation/           ← rendered from the `add-validation-...` notebooks
├── reference/            ← API docs auto-generated via autodoc
└── adr/                  ← keeps existing ADR markdown
```

Each `theory/*.rst` chapter follows the same template:

1. **Inputs** — the function signature in plain language.
2. **Equation** — LaTeX-rendered, numbered, with a citation to
   the original paper.
3. **Assumptions + limits** — when the model breaks down.
4. **Calibration** — what data was used to fit constants, what
   the residual error is, how to re-calibrate.
5. **Code reference** — link to the implementation file.
6. **Test reference** — link to the regression test.

Auto-publishes on every push to `main` and on every release tag.

## Impact

- **New deps** (extra `[docs]`): `sphinx`, `sphinx-rtd-theme`,
  `sphinx-autodoc-typehints`, `myst-parser`, `nbsphinx`.
- **CI**: new `.github/workflows/docs.yml` builds + pushes to
  `gh-pages/docs/`.
- **Cross-references**: each theory page hyperlinks to the
  implementation + test, and the source files gain a `# See:
  https://magnadesign.dev/theory/dowell.html` comment block at
  the top of each module.
- **Validation integration**: the `validation/<id>/notebook.ipynb`
  files are rendered as docs pages too via `nbsphinx`, so the
  predicted-vs-measured plots live alongside the theory.
- **No physics changes** — this codifies what already exists.
- **Effort**: ~2 weeks (writing well takes time; the Sphinx
  scaffolding is 1 day).
- **Capability added**: `theory-docs`.
