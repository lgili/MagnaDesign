# Tasks — Protect & surface positioning differentials

## 1. Documentation

- [x] 1.1 `docs/POSITIONING.md` — comparison matrix (rows: differentials;
      columns: us vs FEMMT, MAS, AI-mag, Frenetic, Magnetics Designer,
      Coilcraft selector). Use the same matrix already discussed in
      conversation.
- [x] 1.2 `docs/adr/0001-positioning.md` — Architecture Decision Record
      explaining: context, decision (specialise on PFC + BR market +
      polished UX), consequences (won't try to compete with FEMMT on FEM,
      will adopt MAS rather than build our own schema, etc.).
- [x] 1.3 `CONTRIBUTING.md` with a "Scope guardrails" section listing
      the seven differentials and a "When to say no" rubric for PRs.

## 2. README rework

- [x] 2.1 Hero block above install: "What this tool does that others
      don't" — 3-bullet pitch grounded in the differentials.
- [x] 2.2 Move install instructions below the differential pitch.
- [x] 2.3 Add a "How we differ from open-source alternatives" section
      linking to `docs/POSITIONING.md`.

## 3. About dialog

- [x] 3.1 `ui/about_dialog.py::AboutDialog(QDialog)`:
      - logo / app name / version
      - short pitch paragraph
      - comparison table (small) generated from the same data as
        `docs/POSITIONING.md` (single source of truth)
      - link buttons for each external project (open in browser)
- [x] 3.2 `Help → Sobre` menu in main window.

## 4. project.md

- [x] 4.1 Add a "Why this exists" intro paragraph to
      `openspec/project.md` so future AI sessions inherit the positioning
      context immediately.

## 5. Testing

- [x] 5.1 Render-test: AboutDialog mounts offscreen and shows all
      seven differentials.
- [x] 5.2 Lint-test: README contains a "Why this matters" header before
      the "Install" header (simple grep).

## 6. Maintenance cadence

- [x] 6.1 Calendar reminder (manual): every six months, re-run the
      `docs/POSITIONING.md` matrix to verify our differentials still
      hold (open-source moves; FEMMT may add cost, etc.).
