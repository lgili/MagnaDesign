"""Sphinx config — MagnaDesign documentation site.

Builds via ``sphinx-build -b html docs docs/_build/html`` (or
``make -C docs html``). The CI workflow in
``.github/workflows/docs.yml`` (added by the
``add-theory-of-operation-docs`` change) auto-publishes to
GitHub Pages on every push to ``main``.

Do not edit auto-generated content. The Theory chapters under
``theory/`` are hand-written and survive every rebuild.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable for autodoc — the source layout
# is ``src/pfc_inductor/``; Sphinx runs from ``docs/`` by
# default, so we add the repo root to sys.path.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))


# -- Project information ----------------------------------------------------
project = "MagnaDesign"
author = "MagnaDesign maintainers"
copyright_line = "MagnaDesign maintainers — MIT licence"
copyright = copyright_line  # Sphinx config-key needs this name

# Pull the package version from importlib.metadata so the docs
# never drift from pyproject.toml's authoritative number.
try:
    from importlib.metadata import version as _version

    release = _version("magnadesign")
    version = ".".join(release.split(".")[:2])
except Exception:
    release = "0.0.0"
    version = "0.0"


# -- General configuration --------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",  # Google-style docstrings
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "myst_parser",  # Markdown support
    "sphinx_copybutton",  # copy-on-hover for code blocks
    "sphinxcontrib.mermaid",  # Mermaid block diagrams
]

# autodoc / autosummary
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autosummary_generate = True
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False

# MyST parser — let Markdown sources mix freely with reST.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
myst_enable_extensions = [
    "colon_fence",  # ::: admonitions
    "deflist",
    "linkify",
    "smartquotes",
    "substitution",
    "tasklist",
]

# Cross-link external projects.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "scipy": ("https://docs.scipy.org/doc/scipy", None),
    "matplotlib": ("https://matplotlib.org/stable", None),
}

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "**/.ipynb_checkpoints",
]


# -- HTML output ------------------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_title = f"MagnaDesign {release}"
html_static_path = ["_static"]
html_show_sourcelink = True
html_show_copyright = True

html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "prev_next_buttons_location": "both",
}

# Make math render via MathJax 3 with the LaTeX preamble we
# expect in the Theory chapters (B, H, L, etc. are Greek-
# heavy; MathJax handles unicode mathvariant cleanly).
mathjax3_config = {
    "tex": {
        "macros": {
            "RR": "{\\mathbb{R}}",
            "uH": "{\\mu \\mathrm{H}}",
            "Bsat": "{B_{\\mathrm{sat}}}",
            "Brem": "{B_{\\mathrm{r}}}",
            "Hc": "{H_{\\mathrm{c}}}",
        },
    },
}


# -- Copybutton -------------------------------------------------------------
# Strip ``$`` and ``>>>`` prefixes so users can copy-paste shell /
# REPL examples directly. Otherwise the prompt characters end up
# in their terminal.
copybutton_prompt_text = r">>> |\.\.\. |\$ |In \[\d*\]: |    \.\.\.\.: "
copybutton_prompt_is_regexp = True
