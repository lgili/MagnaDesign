"""Sphinx config — MagnaDesign documentation site.

Builds via ``sphinx-build -b html docs docs/_build/html`` (or
``make -C docs html``) for a single-version preview, or via
``sphinx-multiversion docs docs/_build/multi`` to render every
git tag matching ``v*`` plus the ``main`` branch as separate
sub-sites under ``docs/_build/multi/<ref>/``. The CI workflow in
``.github/workflows/docs.yml`` runs the multi-version build on
every release and publishes to GitHub Pages.

Theme: Furo (https://pradyunsg.me/furo/) — modern, dark-mode-
ready, mobile-friendly, used upstream by pip / urllib3 / attrs /
many high-traffic Python projects. Replaced ``sphinx-rtd-theme``
which still looks like 2014.

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
    # ``sphinx_multiversion`` is conditionally loaded — it isn't a
    # hard dependency for a single-version preview build (the dev
    # who only wants to preview ``main`` shouldn't have to install
    # it). When the package isn't importable we silently drop the
    # extension and only the multi-version build path breaks; the
    # plain ``sphinx-build`` flow keeps working.
]
try:
    import sphinx_multiversion  # noqa: F401

    extensions.append("sphinx_multiversion")
except ImportError:
    pass

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
html_theme = "furo"
html_title = f"MagnaDesign {release}"
html_static_path = ["_static"]
html_show_sourcelink = True
html_show_copyright = True

# Furo theme tuning — clean light + dark palette tied to the
# MagnaDesign brand accent (matches ``Palette.accent`` in
# ``src/pfc_inductor/ui/theme.py``). The ``announcement`` slot
# carries the unstable-API warning until v1.0 ships.
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view", "edit"],
    "source_repository": "https://github.com/lgili/MagnaDesign/",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_css_variables": {
        # Brand accent — ``#3b82f6`` (Linear-blue) from the app
        # palette. Keep both modes' accent identical so a user
        # toggling the theme doesn't see the navigation links
        # shift colour.
        "color-brand-primary": "#3b82f6",
        "color-brand-content": "#3b82f6",
        "color-admonition-background": "#f4f6fb",
    },
    "dark_css_variables": {
        "color-brand-primary": "#60a5fa",
        "color-brand-content": "#60a5fa",
        "color-background-primary": "#0f1115",
        "color-background-secondary": "#16181d",
        "color-foreground-primary": "#e6e8ee",
        "color-admonition-background": "#1c1f26",
    },
    # Footer icons — easy way to expose the GitHub repo from the
    # sidebar without writing a custom template.
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/lgili/MagnaDesign",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" '
                'stroke-width="0" viewBox="0 0 16 16">'
                '<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 '
                "3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-"
                ".01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-"
                ".48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
                "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-"
                ".87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-"
                "1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 "
                "2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 "
                "1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51"
                ".56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29."
                "25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15."
                '46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>'
                "</svg>"
            ),
            "class": "",
        },
    ],
}

# ---------------------------------------------------------------------------
# Multi-version configuration (read by ``sphinx-multiversion``)
# ---------------------------------------------------------------------------
# Build every git tag matching ``v*.*.*`` (release tags) plus the
# ``main`` branch. The latest tag becomes the default the GitHub
# Pages root redirects to — see the workflow's redirect step.
smv_tag_whitelist = r"^v\d+\.\d+\.\d+$"
smv_branch_whitelist = r"^main$"
smv_remote_whitelist = r"^origin$"
smv_released_pattern = r"^refs/tags/v\d+\.\d+\.\d+$"
smv_outputdir_format = "{ref.name}"  # build to docs/_build/<branch-or-tag>/

# Sidebar template ordering — Furo's defaults are
# ``brand``/``search``/``scroll-start``/``sidebar-nav-tree``/
# ``scroll-end``. Slot ``version-selector.html`` between brand
# and search so the selector sits prominently at the top of
# the sidebar without competing with navigation real estate.
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/version-selector.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
    ],
}

# Pull our small extra stylesheet into every page so the version
# selector's dropdown picks up the Furo CSS variables.
html_css_files = ["version-selector.css"]

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
