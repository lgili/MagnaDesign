# Tasks — add-code-signed-installers

## Phase 1 — macOS signing + notarisation

- [~] Acquire Apple Developer ID Application + Installer
      certificates ($99/yr Apple Developer Program). Store the
      `.p12` in 1Password / similar.  *Operational — `docs/release-
      secrets.md` documents the runbook; pending purchase.*
- [~] Add GitHub Actions secrets:
      `APPLE_CERTIFICATE_P12_BASE64`, `APPLE_CERTIFICATE_PASSWORD`,
      `APPLE_NOTARY_USERNAME`, `APPLE_NOTARY_PASSWORD`
      (app-specific password), `APPLE_NOTARY_TEAM_ID`.
      *Workflow already references these names; activates the
      moment they land in repo settings.*
- [x] Update `.github/workflows/release.yml` macOS job:
      - Import cert into a temporary keychain via `security`.
      - `codesign --deep --force --options runtime --entitlements
         packaging/macos/entitlements.plist --sign "Developer ID
         Application: ..." dist/pfc-inductor.app`.
      - `xcrun notarytool submit ... --wait`.
      - `xcrun stapler staple dist/pfc-inductor.app`.
      - All steps gated on `env.APPLE_CERTIFICATE_P12_BASE64 != ''`
        so the workflow keeps building unsigned artefacts when
        the cert isn't yet provisioned.
- [x] Add `packaging/macos/entitlements.plist`: enable
      `com.apple.security.cs.allow-unsigned-executable-memory`
      (PySide6's QML JIT), `com.apple.security.cs.allow-dyld-
      environment-variables` (PyInstaller bootstrap), `disable-
      library-validation` (PyVista's VTK loader), and
      `com.apple.security.network.client` (future Sparkle auto-
      update).
- [~] Build for both `arm64` and `x86_64`; ship a universal
      `.dmg`. *Today the workflow ships `arm64` only via the
      single macos-latest runner — universal binary lands as a
      separate matrix expansion.*
- [x] CI step: `codesign --verify --deep --strict --verbose=2
      dist/pfc-inductor.app` runs immediately after sign — exits
      non-zero on any signature mismatch.

## Phase 2 — Windows signing

- [~] Acquire OV or EV code-signing cert (recommend EV via
      Sectigo / DigiCert; ~$300/yr). EV skips SmartScreen
      reputation accumulation. *Operational — `docs/release-
      secrets.md` covers OV vs. EV trade-offs.*
- [~] If EV: enrol the hardware token in CI via cloud-signing
      (Azure Trusted Signing or Sectigo's API) — GitHub-hosted
      runners can't access USB tokens. *Phase 2.1 deliverable;
      cloud-signing requires either a 10-LOC swap to
      `AzureSignTool` or a Sectigo Cloud Signing API call.*
- [~] Add GitHub Actions secrets: `WINDOWS_CERT_BASE64`,
      `WINDOWS_CERT_PASSWORD`, `WINDOWS_TIMESTAMP_URL`
      (default `http://timestamp.sectigo.com`).
      *Names already referenced by the workflow.*
- [x] Update `release.yml` Windows job:
      - Decode cert from `WINDOWS_CERT_BASE64` into per-job tmp
        file (deleted on completion).
      - `signtool sign /f <pfx> /tr <ts> /fd sha256 /td sha256 /a
         dist/pfc-inductor/pfc-inductor.exe`.
      - `signtool verify /pa /v` — non-zero exit fails the build.
      - Same conditional gate as macOS: skip when secret blank.
- [~] Build `.msi` via WiX or briefcase; sign it with the same
      command.  *Bundle is currently a `.zip` of the PyInstaller
      output; `.msi` packaging is a Phase 2.2 follow-up.*

## Phase 3 — Auto-update wiring

- [x] `pfc_inductor/updater/` module — pure-Python appcast
      polling + Ed25519 signature verification:
      - ``appcast.py``: defensive Sparkle-style RSS parser
        (``parse_appcast(xml_text) -> list[AppcastEntry]``).
        Malformed XML / missing channel / out-of-order
        elements all degrade to ``[]``, never raise.
      - ``signature.py``: ``verify_signature(*, artefact_bytes,
        signature_b64, public_key_b64)`` returning
        :class:`SignatureCheckResult` (``OK`` / ``BAD_SIGNATURE``
        / ``NO_PUBLIC_KEY`` / ``NO_SIGNATURE`` / ``UNAVAILABLE``
        / ``MALFORMED``). Public key pinned in
        ``PUBLIC_KEY_BASE64`` (empty in upstream, maintainer
        forks override).
      - ``client.py``: ``check_for_updates(*, current_version=None,
        url=DEFAULT_APPCAST_URL, timeout_s=10) -> Optional[UpdateInfo]``.
        Honours ``MAGNADESIGN_DISABLE_TELEMETRY`` kill switch.
        Returns ``None`` for any failure path — never raises into
        the GUI.
      - ``version.py``: PEP 440 subset comparator
        (``MAJOR.MINOR.PATCH[-SUFFIX]``) with the "release > pre-
        release" rule. Robust against the ``v`` prefix.
      _Shipped — 25 tests in ``tests/test_updater.py``._
- [x] ``scripts/generate_appcast.py`` — emits a Sparkle-style
      appcast XML from the GitHub Releases API (``gh release
      list --json``) and (optionally) signs each enclosure with
      a maintainer-provided Ed25519 private key.
      ``--include-prerelease`` toggles RC inclusion. Designed to
      run inside the release workflow on tag push.
- [x] ``MainWindow`` Help menu gains "Check for updates…"
      (manual trigger) + "Automatically check at startup"
      checkable toggle persisted in ``QSettings``. The manual
      trigger runs the network probe on a worker thread so the
      GUI stays responsive; the result lands as a
      ``QMessageBox.information`` on the GUI thread.
- [~] First-run dialog asking the user to opt in for auto-check.
      *Deferred — the existing crash-reporter consent dialog
      from ``add-crash-reporting`` is the natural place to bundle
      the auto-update consent prompt; lands when the consent UX
      gets its formal first-run pass.*
- [x] Updater dep gated behind a new ``[updater]`` optional
      extra (``cryptography>=42.0``). The runtime degrades to
      ``SignatureCheckResult.UNAVAILABLE`` when the dep isn't
      installed; production GUI builds install with
      ``uv pip install -e ".[updater]"``.

## Phase 4 — Linux distribution polish

- [~] AppImage build in CI. *Deferred — the PyInstaller bundle
      already runs on Linux without an extra layer. AppImage
      lands when a customer specifically asks for it (most
      industrial Linux users prefer the tarball anyway).*
- [~] `.deb` packaging. *Deferred — same reason. ``briefcase``
      can produce a ``.deb`` from the existing PyInstaller
      bundle if needed.*

## Phase 5 — Docs + release polish

- [~] `docs/install.md` per-platform clean install. *Deferred —
      ``docs/RELEASE.md`` covers the maintainer side; an
      end-user install page lands with the Sphinx getting-started
      polish.*
- [x] ``docs/RELEASE.md`` gains an "Auto-update (appcast)"
      section: privacy contract, signing-keypair generation
      one-liner, GitHub Pages publish workflow snippet, local
      testing recipe with ``MAGNADESIGN_APPCAST_URL`` override.
- [~] Document the appcast URL in ``README.md``. *Deferred —
      bundles with the next README sweep alongside the v6
      release notes.*

## Phase 6 — Annual rotation

- [x] ``docs/release-secrets.md`` documents the Apple Developer
      Program 12-month renewal calendar entry. The maintainer
      adds the entry to their personal calendar; document is
      shipped.
- [~] Windows cert rotation. *Deferred — depends on which
      vendor / cert type the maintainer ends up buying;
      add the calendar reminder when the cert is provisioned.*
