# Tasks — add-theory-of-operation-docs

## Phase 1 — Sphinx scaffolding

- [ ] Add `[docs]` extra to `pyproject.toml`:
      `sphinx >= 7`, `sphinx-rtd-theme`, `sphinx-autodoc-typehints`,
      `myst-parser`, `nbsphinx`, `sphinx-copybutton`,
      `sphinxcontrib-mermaid` (block diagrams).
- [ ] `docs/conf.py`: enable autodoc, autosummary, intersphinx
      (Python stdlib + numpy + scipy), MathJax for LaTeX.
- [ ] `docs/index.rst`: skeleton TOC pointing to the four
      sections below.
- [ ] `make html` works locally; `pre-commit` hook ensures docs
      build on every commit touching `docs/` or any `*.py` with
      a public docstring.

## Phase 2 — Getting-started chapter

- [ ] Migrate the current README "Why this exists" + feature
      matrix to `docs/getting-started/index.rst`.
- [ ] `install.rst`: per-platform install (signed installer when
      that lands; pip / source today).
- [ ] `first-design.rst`: walk a new user through opening
      `examples/600W_PFC_boost.pfc`, hitting Recalculate,
      generating a datasheet — same path as the onboarding tour.
- [ ] `tour.rst`: video gif walkthrough (recorded once, embedded
      via `<img>` in the rst).

## Phase 3 — Theory chapters

For each of the 8 chapters listed in the proposal:

- [ ] `overview.rst`: a Mermaid block diagram of the engine
      pipeline (spec → topology → operating-point → loss → thermal
      coupling → DesignResult).
- [ ] `steinmetz-igse.rst`: derivation, citation
      (Mühlethaler 2012), calibration (12 vendor data-points per
      material), residual error per material.
- [ ] `dowell.rst`: derivation (Dowell 1966), assumptions
      (proximity effect, layer counting), limit (high-density
      Litz where the assumption breaks down).
- [ ] `rolloff.rst`: power-law form
      `μ_frac = 1 / (a + b·H^c)`, calibration against Magnetics
      / Magmattec / Micrometals / CSC datasheets.
- [ ] `thermal.rst`: iterative loop, ρ_cu(T) feedback,
      convergence criterion, default convection coefficient
      assumption.
- [ ] `anhysteretic-bh.rst`: small-signal µ integration to trace
      the operating-point B-H loop; difference vs. major loop.
- [ ] `feasibility.rst`: Tier-0 envelope check formulae (bobbin
      fit, Bsat headroom, AL plausibility) with numerical
      thresholds.
- [ ] `compliance.rst`: derivation of the IEC 61000-3-2 limit
      table from the standard, with the per-class limits tabled
      and the line-cycle harmonic computation methodology.

Each chapter ends with a **"Code reference"** box linking to the
implementation file + line number, and a **"Tests"** box linking
to the regression test.

## Phase 4 — Topology pages

- [ ] `topology/boost-ccm.rst`: derivation of the CCM
      operating-point equations, switching events, ripple shape.
- [ ] `topology/line-reactor.rst`: 60 Hz path, harmonic content
      from rectifier loading, %Z impedance derivation.
- [ ] `topology/passive-choke.rst`: 50/60 Hz path, IEC 61000-3-2
      Class A loading, design margin recommendations.

## Phase 5 — Validation integration

- [ ] `docs/validation/index.rst`: TOC of validated reference
      designs.
- [ ] Each notebook from `add-validation-reference-set` is
      rendered as `docs/validation/<id>.ipynb` via `nbsphinx`.
- [ ] Cross-link: each theory chapter that the design exercises
      gets a "Validated against: <id>" footer.

## Phase 6 — API reference

- [ ] `reference/index.rst` with `autosummary` directives over the
      public modules: `models`, `physics`, `topology`, `design`,
      `optimize`, `optimize.cascade`, `report`, `compliance`,
      `worst_case`, `acoustic`, `manufacturing`, `cli`.
- [ ] Type hints rendered nicely via `sphinx-autodoc-typehints`.

## Phase 7 — Deploy

- [ ] `.github/workflows/docs.yml`: build on every push to `main`,
      deploy to `gh-pages` branch, set CNAME to
      `magnadesign.dev/docs` (when DNS configured).
- [ ] Add a `docs/_static/version.json` that the app's About
      dialog can poll to display "Latest docs: vX.Y.Z" with a
      hyperlink.
- [ ] Update `README.md` with a "📖 Docs" badge linking to the
      hosted site.

## Phase 8 — Maintenance

- [ ] Add a `docs/contributing.md`: when you add a physics module,
      add a theory chapter the same PR. CI fails if a new public
      function has no docstring.
- [ ] CHANGELOG entry referencing the docs site URL.
