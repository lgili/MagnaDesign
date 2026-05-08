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

- [ ] `pfc_inductor/updater/` module:
      - Pure-Python helper that fetches `appcast.xml` from
        GitHub Pages, compares versions, optionally downloads
        the new release.
      - Platform-specific runners: on macOS shells out to
        Sparkle's `sparkle-cli`; on Windows uses the bundled
        Squirrel updater.
      - Linux: returns "not supported" (apt / AppImage handle
        their own updates).
- [ ] `appcast.xml` generator: an extra step in `release.yml`
      that publishes a signed appcast (signed via Sparkle's
      `sign_update`) to `gh-pages/appcast.xml`.
- [ ] `MainWindow` Help menu gains:
      - "Check for updates…" (manual trigger).
      - "Automatically check at startup" toggle saved to
        QSettings.
- [ ] First-run dialog: ask the user opt-in for auto-check.

## Phase 4 — Linux distribution polish

- [ ] Build an AppImage in CI (`appimagetool`); GPG-sign the
      AppImage; publish the signature alongside.
- [ ] Provide a `.deb` for Debian/Ubuntu via `briefcase` or
      `dh-virtualenv` (lower priority — AppImage covers most
      industrial users).

## Phase 5 — Docs + release polish

- [ ] `docs/install.md`: per-platform install steps with the
      Gatekeeper / SmartScreen "right-click → Open" caveat
      removed (no longer needed).
- [ ] Update `docs/RELEASE.md` with the new signing prerequisites
      and the certificate-rotation calendar.
- [ ] Document the `appcast.xml` URL in `README.md` so users
      can sanity-check it.

## Phase 6 — Annual rotation

- [ ] Calendar reminder: Apple cert renews yearly, Windows cert
      every 1–3 years. Document in `docs/RELEASE.md` who's on
      the rotation hook.
