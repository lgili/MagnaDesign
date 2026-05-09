# MagnaDesign — Internal training deck

Beamer-based slide deck for the internal course on the
**MagnaDesign** desktop tool. Custom metropolis-style
styling using only base beamer (no extra LaTeX packages
to install). Three real-world reference designs (Boost
PFC 1.5 kW, 3φ line reactor 22 kW, flyback DCM 65 W) feed
two Python harnesses that auto-generate every figure in
the deck.

## Layout

```
presentation/
├── main.tex                          Slide deck — 42 pages, English
├── Makefile                          make / make screenshots / clean
├── README.md                         this file
├── theme/
│   └── magnadesign-colors.tex        palette synced with the app UI
├── sections/                         (reserved — currently empty)
├── scripts/
│   ├── build_screenshots.py          real-widget renders (3 RefDesigns)
│   └── build_placeholders.py         analytic mock-ups for screens
│                                     where the live widget needs
│                                     more runtime than offscreen Qt
│                                     can provide
└── figures/                          all PNGs / PDFs the .tex includes
```

## How to build

### Requirements

* A working TeX install with `pdflatex`, `beamer`, `xcolor`,
  `tikz`, `booktabs`, `listings`. BasicTeX is enough — no
  extra packages required.
* Python 3.12 with the project venv at `../.venv/bin/python`
  (PySide6 + matplotlib + numpy + the `pfc_inductor` package
  itself).

### Compile the PDF

```bash
cd presentation
make           # → main.pdf  (two pdflatex passes for the TOC)
make clean     # → drop .aux/.log/.toc, keep main.pdf and figures/
make distclean # → drop everything, including figures/
```

### Regenerate every figure

If you change a widget in the app, the reference designs in
the harness, or any of the synthetic placeholders:

```bash
make screenshots   # runs build_screenshots.py + build_placeholders.py
make               # rebuild the PDF with the refreshed images
```

The two harnesses are chained in the Makefile so a single
target refreshes everything.

## The three reference designs

| # | Topology | Spec | Market reference |
|---|---|---|---|
| 1 | **Boost PFC CCM** | 85–265 V$_{rms}$ → 400 V, 1.5 kW, 100 kHz | TI UCC28019 reference design + Magnetics Kool-Mu 0077439A7 toroid |
| 2 | **3φ line reactor** | 400 V$_{LL}$, 22 kW, 32 A, 3 % impedance | ABB MCB-32 / Schaffner FN3220 series |
| 3 | **Flyback DCM** | 85–265 V$_{rms}$ → 19 V/3.4 A, 65 W, 65 kHz | TI UCC28911 EVM (laptop adapter), PQ20/16 N97 |

The three were chosen so that the deck exercises every
distinct capability of the app:

* **Boost CCM** drives all five FEA-dialog tabs, the swept
  FEA L(I) sweep, and the operating-point B-H curve. The
  "complete" demo case.
* **Line reactor** activates the IEC 61000-3-2 harmonics
  card and demonstrates the FEMMT → FEMM legacy auto-
  fallback for designs with N > 150 turns.
* **Flyback** triggers the dual-winding render (primary +
  secondary in distinct colours) on the geometry view and
  the DCM-mode current waveform.

## Replacing rendered figures with live-app captures

Most figures are rendered automatically (real widgets via
the harness, or analytic mock-ups). A few — Pareto front,
Cascade Top-N table, Compare dialog, Export HTML preview,
the 3D viewer — are mock-ups that approximate the real
visuals. To replace them with real screenshots from the
running app:

1. Open the app: `python -m pfc_inductor`
2. Load (or recreate) one of the reference designs
3. Capture with `Cmd-Shift-4` (macOS) or Snipping Tool
   (Windows)
4. Save the PNG into `figures/` using **the same filename**
   as the existing mock-up
5. Run `make` to rebuild — the LaTeX `\includegraphics`
   picks up the new file by name

Filenames the deck consumes:

```
example1_spec.png             Spec drawer (boost)
example1_formas_onda.png      Waveforms card (boost)
example2_spec.png             Spec drawer (line reactor)
example2_fea_dispatch.png     Auto-fallback flowchart
example3_spec.png             Spec drawer (flyback)
example3_formas_onda.png      Waveforms card (flyback)
example3_fea_summary.png      FEA Summary tab (flyback)
feature_otimizador_pareto.png Pareto front
feature_cascade.png           Cascade Top-N table
feature_compare.png           Compare-designs dialog
feature_export.png            Datasheet HTML render
feature_3d.png                Qt3D viewer
logo-placeholder.pdf          App logo
```

## Visual identity

`theme/magnadesign-colors.tex` re-skins beamer with the
exact palette the running app uses (`accent_violet`,
`warning`, `success`, `danger`, etc., extracted from
`src/pfc_inductor/ui/theme.py`). If you change the app's
palette, refresh this file — it's the single source of
truth for the deck's colours.

## Estimated talk length

~ 30–45 minutes with Q&A (36 content slides + section
dividers, 42 pages total). Expand or compress sections by
adding / removing frames within the relevant `\section{...}`
group; the table of contents on slide 2 only lists section
headings, so it stays clean as you iterate.
