# Sphinx build helper. Run ``make html`` (or ``make help``) from
# the repo root's ``docs/`` directory.
#
# CI invokes ``sphinx-build`` directly via the docs.yml workflow.
# This file is for the maintainer's local builds.

SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help html clean linkcheck

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

html:
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)
	@echo "Site rendered at $(BUILDDIR)/html/index.html"

linkcheck:
	@$(SPHINXBUILD) -b linkcheck "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck" $(SPHINXOPTS)

clean:
	@rm -rf "$(BUILDDIR)"
