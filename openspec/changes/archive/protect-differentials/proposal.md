# Protect & surface our positioning differentials

## Why

After surveying the open-source landscape (`FEMMT`, `OpenMagnetics`,
`AI-mag`, `Princeton MagNet`, etc.), the technical scope overlap is
real. We risk drifting into a "yet another FEM toolbox" or "yet another
schema" if we don't stay deliberate about what makes us unique.

Our seven defensible differentials, in priority order:

1. **PFC topology specialisation** — boost CCM and passive line choke
   maths embedded; nobody else does this end-to-end.
2. **Cost model in the optimizer** — closed-source competitors (Frenetic
   AI) charge for this; FEMMT/MAS don't have it.
3. **Litz optimizer with Sullivan criterion** — built-in recommend +
   save-as-new-wire flow.
4. **Multi-design side-by-side compare** with diff-aware highlighting
   and HTML export.
5. **B–H operating-loop visualisation** at the design point.
6. **Polished PySide6 UX** with light + dark themes, designed for
   engineering density, not generic Qt look.
7. **Brazilian vendor data** (Thornton, Magmattec) and Portuguese-first
   UI — a market neither North-American nor European tools serve.

This change codifies these differentials and surfaces them in the app
and the docs so contributors don't accidentally trade them away.

## What changes

- New `docs/POSITIONING.md` with the differential matrix vs. FEMMT,
  OpenMagnetics MAS, AI-mag, Frenetic, Magnetics Inc Designer.
- Re-pointed README hero section: "What this app does that others
  don't", before the install instructions.
- `CONTRIBUTING.md` with an explicit "scope guardrails" section.
- New "Sobre" dialog (Help → Sobre) showing the comparison table inline
  for the user; serves as both credit and as a reminder of the value
  delivered.
- A short "Why this app exists" paragraph at the top of `openspec/project.md`.
- ADR (`docs/adr/0001-positioning.md`) capturing the strategic decision
  to specialise rather than generalise.

## Impact

- Affected capabilities: NEW `positioning`
- Affected modules: NEW `ui/about_dialog.py`, README, NEW
  `docs/POSITIONING.md`, NEW `docs/adr/0001-positioning.md`,
  `openspec/project.md`, NEW `CONTRIBUTING.md`,
  `ui/main_window.py` (Help menu).
- No new code dependencies.
- This is the lightest of the four proposals (no test work) but the most
  important for project longevity.
