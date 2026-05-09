# MagnaDesign training-deck build
#
# Targets
#   make                → build main.pdf (default)
#   make screenshots    → regenerate figures/ from the harness
#   make clean          → remove build artefacts (keeps figures/)
#   make distclean      → also drop figures/
#   make watch          → continuous rebuild on .tex / figure changes
#
# Toolchain
#   - latexmk + lualatex (lualatex is needed by metropolis for
#     Fira Sans; pdflatex falls back to a serif face that loses
#     the modern look).
#   - Python 3.12 + the project's venv at ../.venv/bin/python.

PDFLATEX    ?= pdflatex
PDFLATEX_FLAGS ?= -interaction=nonstopmode -halt-on-error \
                  -file-line-error
PYTHON      ?= ../.venv/bin/python
HARNESS     := scripts/build_screenshots.py

MAIN        := main
PDF         := $(MAIN).pdf
TEX_SOURCES := $(MAIN).tex $(wildcard sections/*.tex) \
               $(wildcard theme/*.tex)
FIGS        := figures

# Default — build the PDF.
all: $(PDF)

# Two passes so the table of contents resolves correctly. First
# run produces the .aux/.toc; second run picks them up. Beamer
# also benefits from the second pass for inline page-numbering.
$(PDF): $(TEX_SOURCES) | $(FIGS)
	$(PDFLATEX) $(PDFLATEX_FLAGS) $(MAIN).tex
	$(PDFLATEX) $(PDFLATEX_FLAGS) $(MAIN).tex

# Screenshots — three harnesses chained, in order:
#   1. build_screenshots.py → real widget renders driven by the
#                              three RefDesigns. Produces the
#                              per-example geometry, B-H, swept,
#                              loss-bar etc.
#   2. build_placeholders.py → analytic mockups for the few
#                              screens that no live widget covers
#                              (FEA dispatch flowchart, app logo).
#   3. build_gui_renders.py → real GUI captures of the remaining
#                              widgets (SpecDrawer, OtimizadorPage,
#                              CascadePage, CompareDialog,
#                              Viz3DCard, ExportarTab). Runs last
#                              so its captures **overwrite** any
#                              matching placeholder PNGs from
#                              step 2 — every covered widget ends
#                              up showing a real screenshot.
# A single ``make screenshots`` refreshes the whole figures/
# directory.
screenshots:
	$(PYTHON) $(HARNESS)
	$(PYTHON) scripts/build_placeholders.py
	$(PYTHON) scripts/build_gui_renders.py

# Treat figures/ as a directory dependency. The default target
# doesn't run the harness automatically (some users will edit
# figures by hand and don't want them clobbered). Run
# `make screenshots` explicitly before `make` to refresh.
$(FIGS):
	mkdir -p $(FIGS)

clean:
	rm -f $(MAIN).aux $(MAIN).log $(MAIN).out $(MAIN).toc \
	      $(MAIN).nav $(MAIN).snm $(MAIN).vrb \
	      $(MAIN).bbl $(MAIN).blg $(MAIN).synctex.gz

distclean: clean
	rm -f $(PDF)
	rm -rf $(FIGS)

.PHONY: all screenshots clean distclean
