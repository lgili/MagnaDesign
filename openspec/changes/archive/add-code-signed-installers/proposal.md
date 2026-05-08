# Add code-signed installers + auto-update

## Why

The current release pipeline (`.github/workflows/release.yml`)
builds PyInstaller bundles for Linux / macOS / Windows on tag, but
**none of the artefacts are code-signed**. That triggers three
concrete adoption blockers:

1. **macOS Gatekeeper** quarantines the unsigned `.app` and
   refuses to run it from Finder; the user has to right-click →
   Open → "Allow" once, and on Sequoia (macOS 15) even that path
   gets thinner. IT-managed laptops in industrial settings ban
   unsigned binaries outright.
2. **Windows SmartScreen** flags the unsigned `.exe` as
   "potentially harmful" until enough installs accumulate
   reputation. Engineers in regulated industries can't get
   approval from corporate IT for a SmartScreen-flagged binary.
3. **No auto-update mechanism** — a user who installs v0.5 has
   no path to v0.6 short of manually re-downloading. For a tool
   shipping every couple of weeks this is a friction multiplier
   and a security liability (no way to push a CVE patch).

For an industrial team to standardise on MagnaDesign, the
installers have to land like a normal commercial app: signed,
notarised, with a "Check for updates" menu entry. The cost is
~$400/year for the certificates and a few days of one-off work.

## What changes

Three deliverables, releasable independently:

1. **macOS code-sign + notarisation**:
   - GitHub Actions secrets for an Apple Developer ID Application
     certificate and notarisation credentials.
   - `codesign --options runtime --entitlements …` on the `.app`,
     then `xcrun notarytool submit` and `stapler` on the result.
   - Distribute as a `.dmg` with the signed `.app` inside.
   - Apple Silicon (`arm64`) + Intel (`x86_64`) both signed.

2. **Windows Authenticode signing**:
   - GitHub Actions secret for an OV (Organisation Validation) or
     EV (Extended Validation) code-signing cert. EV recommended:
     it skips the SmartScreen reputation curve.
   - `signtool sign /tr http://timestamp.… /fd sha256 /td sha256`
     on the bundled `.exe` and the installer (`.msi`).
   - Distribute the `.msi` as primary, with a fallback signed
     `.exe`.

3. **Sparkle / Squirrel auto-update**:
   - macOS: bundle Sparkle.framework. App polls a signed
     `appcast.xml` published to GitHub Pages on tag.
   - Windows: bundle Squirrel.Windows in the `.msi`. Same
     `appcast.xml` mechanism.
   - Linux: skip — user runs from package manager / AppImage.
   - The app gains a "Check for updates…" menu entry under
     **Help** and an opt-in "Auto-check at startup".

## Impact

- **CI**: extends `.github/workflows/release.yml` with a sign +
  notarise stage per platform.
- **Secrets**: 4 new GitHub repo secrets (Apple cert, Apple
  notarisation creds, Windows cert, Windows cert password).
  Documented under `docs/release-secrets.md` (private).
- **No code changes** for signing itself — it's a pure pipeline
  task. Auto-update *is* a code change (~150 LOC in `ui/updater.py`
  + small App / Window changes).
- **Operational cost**: ~$400 / year for certificates (Apple
  Developer Program $99/yr; Sectigo OV cert ~$80/yr or EV
  ~$300/yr).
- **External dependency**: Apple's notarytool is rate-limited
  (≤ 75 submissions/day); Sectigo ships EV cert on a hardware
  USB token unless using their cloud-signing API.
- **Tests**: integration test in CI that the released binary's
  signature is valid (`codesign --verify --deep --strict` /
  `signtool verify /pa /v`).
- **Capability added**: `signed-distribution`,
  `auto-update`.
- **Effort**: 1 week (signing pipeline) + 4 days (auto-update).
