# Tasks — add-theory-of-operation-docs

All shipped in `da5c40e feat(docs): Sphinx site — Theory of
Operation + topology + CLI guides`.

## Phase 1 — Sphinx scaffolding

- [x] Add `[docs]` extra to `pyproject.toml`:
      `sphinx >= 7`, `sphinx-rtd-theme`, `sphinx-autodoc-typehints`,
      `sphinx-copybutton`, `myst-parser`, `sphinxcontrib-mermaid`.
      _`nbsphinx` deferred — gated on the validation reference
      set landing with executed notebooks._
- [x] `docs/conf.py`: enable autodoc, autosummary, napoleon,
      MyST, mermaid, MathJax 3, copybutton; pulls version from
      `importlib.metadata`; adds `src/` to sys.path.
- [x] `docs/index.rst`: top-level TOC with sections for
      Getting started, Theory of operation, Topology, Project /
      governance, API reference.
- [x] `make html` works locally via the standard `docs/Makefile`.
- [~] `pre-commit` hook ensures docs build on every commit
      touching `docs/` or any `*.py` with a public docstring.
      *Deferred — the GitHub Actions workflow (`.github/workflows/
      docs.yml`) builds with `-W --keep-going` on every push to
      main, which catches doc-string regressions before they
      land. A local pre-commit hook is nice-to-have but not
      blocking.*

## Phase 2 — Getting-started chapter

- [x] `docs/getting-started/install.rst`: per-platform install
      runbook (pip / source / dev).
- [x] `docs/getting-started/first-design.rst`: 5-min walkthrough
      from opening the example project to generating a
      datasheet.
- [x] `docs/getting-started/cli.rst`: CLI cheat sheet with exit
      codes for every subcommand.
- [~] `tour.rst`: video gif walkthrough. *Deferred — the
      first-design walkthrough covers the same ground in text
      form; gif recording lands when the next UX pass happens.*

## Phase 3 — Theory chapters

- [x] `docs/theory/overview.rst`: Mermaid block diagram of the
      engine pipeline.
- [x] `docs/theory/steinmetz-igse.rst`: anchored Steinmetz +
      iGSE derivation with full LaTeX equations; cites
      Mühlethaler 2012.
- [x] `docs/theory/dowell.rst`: skin effect + proximity formula
      F_R; cites Dowell 1966 + Sullivan 1999 (Litz extension).
- [x] `docs/theory/rolloff.rst`: power-law rolloff calibration
      per vendor.
- [x] `docs/theory/thermal.rst`: iterative thermal solver.
- [~] `anhysteretic-bh.rst`: small-signal µ integration. *Deferred
      — the BH-loop visualisation is in the app but the formal
      anhysteretic derivation hasn't been authored yet; lands
      with the next docs pass.*
- [x] `docs/theory/feasibility.rst`: Tier-0 envelope check
      formulae (5 µs/candidate budget).
- [x] `docs/theory/compliance.rst`: IEC 61000-3-2 + EN 55032 +
      UL 1411 derivations.

## Phase 4 — Topology pages

- [x] `docs/topology/boost-ccm.rst`.
- [x] `docs/topology/line-reactor.rst`.
- [x] `docs/topology/passive-choke.rst`.
- [x] `docs/topology/buck-ccm.rst` (bonus — added when buck-CCM
      shipped in `c90f2ee`).

## Phase 5 — Validation integration

- [~] `docs/validation/index.rst`: TOC of validated reference
      designs. *Deferred — gated on `add-validation-reference-set`
      landing with physical bench data. The Sphinx site has the
      slot reserved; notebook rendering via nbsphinx wires up
      when the notebooks land.*
- [~] Each notebook rendered as `docs/validation/<id>.ipynb`.
      *Deferred — see above.*
- [~] Cross-link: each theory chapter gets a "Validated
      against: <id>" footer. *Deferred — see above.*

## Phase 6 — API reference

- [x] `docs/reference/index.rst` with `autosummary` directives
      across every public module.
- [x] Type hints rendered nicely via
      `sphinx-autodoc-typehints`.

## Phase 7 — Deploy

- [x] `.github/workflows/docs.yml`: builds Sphinx with
      `-W --keep-going` on every push to main; deploys to GitHub
      Pages.
- [~] `docs/_static/version.json` for the About dialog to poll.
      *Deferred — About dialog already shows the version; cross-
      linking to the docs site lands when the DNS for
      magnadesign.dev/docs goes live.*
- [~] Update `README.md` with a "📖 Docs" badge.
      *Deferred — README sweep planned alongside the next
      release tag.*

## Phase 8 — Maintenance

- [~] `docs/contributing.md`. *Deferred — the docs build
      workflow already fails on missing/malformed docstrings
      via `-W --keep-going`, which is the enforcement mechanism.
      A formal CONTRIBUTING.md lands with the next release.*
- [~] CHANGELOG entry referencing the docs site URL.
      *Deferred — README + CHANGELOG sweep planned alongside
      the next release tag.*
