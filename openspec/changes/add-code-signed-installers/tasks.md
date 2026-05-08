# Tasks — add-code-signed-installers

## Phase 1 — macOS signing + notarisation

- [ ] Acquire Apple Developer ID Application + Installer
      certificates ($99/yr Apple Developer Program). Store the
      `.p12` in 1Password / similar.
- [ ] Add GitHub Actions secrets:
      `APPLE_CERTIFICATE_P12_BASE64`, `APPLE_CERTIFICATE_PASSWORD`,
      `APPLE_NOTARY_USERNAME`, `APPLE_NOTARY_PASSWORD`
      (app-specific password), `APPLE_NOTARY_TEAM_ID`.
- [ ] Update `.github/workflows/release.yml` macOS job:
      - Import cert into a temporary keychain via `security`.
      - `codesign --deep --options runtime --entitlements
         build/macos/entitlements.plist --sign "Developer ID
         Application: ..." dist/MagnaDesign.app`.
      - `xcrun notarytool submit ... --wait`.
      - `xcrun stapler staple dist/MagnaDesign.app`.
      - Build a `.dmg` (via `create-dmg`) and sign it too.
- [ ] Add `build/macos/entitlements.plist`: enable
      `com.apple.security.cs.allow-unsigned-executable-memory`
      (PySide6 needs it) and `com.apple.security.network.client`.
- [ ] Build for both `arm64` and `x86_64`; ship a universal
      `.dmg`.
- [ ] CI step: `codesign --verify --deep --strict --verbose=4
      dist/MagnaDesign.app` — non-zero exit fails the release.

## Phase 2 — Windows signing

- [ ] Acquire OV or EV code-signing cert (recommend EV via
      Sectigo / DigiCert; ~$300/yr). EV skips SmartScreen
      reputation accumulation.
- [ ] If EV: enrol the hardware token in CI via cloud-signing
      (Azure Trusted Signing or Sectigo's API) — GitHub-hosted
      runners can't access USB tokens. If OV: store cert in repo
      secret as base64.
- [ ] Add GitHub Actions secrets: `WINDOWS_CERT_BASE64`,
      `WINDOWS_CERT_PASSWORD`, `WINDOWS_TIMESTAMP_URL`
      (default `http://timestamp.sectigo.com`).
- [ ] Update `release.yml` Windows job:
      - Import cert: `Import-PfxCertificate`.
      - Build `.exe` via PyInstaller.
      - `signtool sign /tr <ts> /fd sha256 /td sha256
         /a dist/MagnaDesign.exe`.
      - Build `.msi` via WiX or [briefcase]; sign it with the
        same command.
- [ ] Verify with `signtool verify /pa /v dist/MagnaDesign.msi`
      — non-zero exit fails the release.

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
