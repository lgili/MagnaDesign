Installation
============

MagnaDesign ships as a code-signed installer for macOS / Windows
and as a source distribution for Linux + advanced users.

Signed installer (recommended)
------------------------------

- **macOS**: download the ``.dmg`` from the `releases page
  <https://github.com/your-org/magnadesign/releases>`_, double-
  click → drag MagnaDesign.app to /Applications. Notarised, no
  Gatekeeper override needed.
- **Windows**: download the ``.msi`` → double-click. Authenticode
  signed with an EV cert, no SmartScreen warning.

The signing pipeline is documented in
``.github/workflows/release.yml`` and gated on the four Apple +
three Windows certificate secrets per
``docs/release-secrets.md``. Until the certs are provisioned the
release ships unsigned binaries — see the runbook for the
operational rollout.

Source install (Linux / dev)
----------------------------

Requires Python 3.11 or 3.12 (FEMMT pins the upper bound).

.. code-block:: console

   $ git clone https://github.com/your-org/magnadesign.git
   $ cd magnadesign
   $ uv venv                       # or python -m venv .venv
   $ uv pip install -e .            # full install (includes FEMMT)
   $ uv pip install -e ".[dev]"     # plus tests + linters

Launch:

.. code-block:: console

   $ magnadesign        # GUI
   $ magnadesign --help  # CLI

CI + headless
-------------

The CLI is fully Qt-free — ``magnadesign sweep`` /
``magnadesign cascade`` / ``magnadesign worst-case`` /
``magnadesign compliance`` run on a headless server without
``QT_QPA_PLATFORM=offscreen`` set.

For test runs:

.. code-block:: console

   $ QT_QPA_PLATFORM=offscreen pytest

The ``add-cli-headless-runner`` proposal in
``openspec/changes/`` documents the full subcommand surface.

Optional extras
---------------

- ``[fea]`` — **No longer needed.** FEMMT is a default dependency
  as of v0.4.10. The extra is kept as an empty alias for backward
  compatibility (existing ``pip install ".[fea]"`` invocations
  still work, just install nothing extra). ONELAB (the gmsh +
  getdp binary blob FEMMT shells out to) is still installed
  separately by the in-app *Settings → FEA* dialog because it's a
  multi-hundred-MB native distribution that doesn't belong in a
  pip wheel.
- ``[dev]`` — pytest + ruff + mypy + black for development.
- ``[docs]`` — Sphinx + RTD theme + extensions for building this
  site locally (``make -C docs html``).
