# Release secrets — code-signing setup runbook

This document tells the maintainer how to provision the four
GitHub Actions secrets the release workflow checks for. The
secrets themselves never leave 1Password / your password
manager; only their *names* are referenced from
``.github/workflows/release.yml``.

Until the secrets exist, the workflow ships **unsigned**
artefacts (current behaviour). The conditional steps in the
workflow no-op cleanly when the secrets are blank.

## macOS — Apple Developer ID + Notarisation

### 1. Enrol in the Apple Developer Program (one-off)

- https://developer.apple.com/programs/ — $99 / year.
- Renewal calendar entry: every 12 months, ~30 days before
  expiry. The certificates auto-revoke on the day; releases
  built after that fail to verify until renewed.

### 2. Generate a Developer ID Application certificate

Inside Xcode → Settings → Accounts → Manage Certificates →
**+** → "Developer ID Application". The CSR is generated
locally; the resulting certificate is added to your login
keychain.

Export the cert + its private key to a ``.p12`` (PKCS#12):

- Keychain Access → My Certificates → "Developer ID
  Application: <Your Name> (<TEAM>)" → right-click → Export.
- Choose a **strong** password (≥ 32 random chars). Save the
  password to 1Password under the entry "MagnaDesign release
  certs".

### 3. Generate an app-specific password for notarytool

- https://appleid.apple.com → Sign-In and Security →
  App-Specific Passwords → "Generate".
- Label: ``magnadesign-notarytool``. Copy the password into
  1Password.
- Note your **Team ID**: Apple Developer portal →
  Membership → "Team ID" (10 alphanumeric chars).

### 4. Configure the GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions → **New
repository secret**:

| Secret name                       | Value                              |
|-----------------------------------|------------------------------------|
| `APPLE_CERTIFICATE_P12_BASE64`    | ``base64 -i devid.p12 -o -``       |
| `APPLE_CERTIFICATE_PASSWORD`      | the .p12 export password            |
| `APPLE_NOTARY_USERNAME`           | your Apple ID email                |
| `APPLE_NOTARY_PASSWORD`           | the app-specific password (step 3) |
| `APPLE_NOTARY_TEAM_ID`            | the 10-char Team ID                |

The release workflow's macOS job picks the secrets up
automatically on the next tag push. Verify with one
``workflow_dispatch`` run before tagging a real release.

## Windows — Authenticode

### 1. Pick OV vs. EV

- **EV** (Extended Validation) — recommended. ~$300 / year
  via Sectigo / DigiCert. SmartScreen reputation is granted
  immediately at sign time, so users never see the
  "unrecognised app" warning.
- **OV** (Organisation Validation) — ~$80 / year. Requires
  weeks-to-months of installs to accumulate SmartScreen
  reputation; users see scary warnings until then.

EV is shipped on a hardware USB token unless you pay extra
for a cloud-signing API. Cloud-signing (Azure Trusted Signing
or Sectigo's new API) is the only option that works with
GitHub-hosted runners — they can't access USB tokens.

### 2. Acquire the certificate

- https://www.sectigo.com/ssl-certificates-tls/code-signing
  (or DigiCert / GlobalSign).
- Identity-verification process: corporate documents,
  notarised signature, a phone interview. Plan ~1–3 weeks.

For OV: export to ``.pfx`` with a strong password, base64-
encode for the ``WINDOWS_CERT_BASE64`` secret.

For EV via Azure Trusted Signing: switch the workflow's
``signtool`` step to ``AzureSignTool`` (10 LOC change,
documented when we provision the cert).

### 3. Configure the GitHub Actions secrets

| Secret name              | Value                                       |
|--------------------------|---------------------------------------------|
| `WINDOWS_CERT_BASE64`    | ``base64 -i codesign.pfx -o -``              |
| `WINDOWS_CERT_PASSWORD`  | the .pfx export password                     |
| `WINDOWS_TIMESTAMP_URL`  | ``http://timestamp.sectigo.com`` (optional)  |

## Sparkle / Squirrel auto-update (Phase 3, separate change)

The signing pipeline above leaves both binaries ready for
Sparkle (macOS) / Squirrel (Windows) to publish update
manifests. That work tracks as Phase 3 in
``openspec/changes/add-code-signed-installers/tasks.md`` and
needs:

- An ``EdDSA`` signing keypair for Sparkle's ``appcast.xml``
  (generated with ``sign_update generate-keys``; public key
  baked into the app, private key as
  ``SPARKLE_PRIVATE_KEY_PEM`` secret).
- An ``appcast.xml`` generator step that publishes to
  ``gh-pages/appcast.xml`` on every release.

Don't add those secrets until the Sparkle integration lands —
they're useless without the in-app updater code.

## Verifying

After the secrets are set, the next release run logs:

- ``::notice::Imported 1 Developer ID identities`` (macOS)
- ``Successfully verified`` from ``signtool verify`` (Windows)

Smoke-test the artefacts on a clean machine:

- macOS: download the .dmg, double-click — it should mount
  without Gatekeeper prompts.
- Windows: download the .exe, double-click — SmartScreen
  should let it run on first launch (EV) or after a couple
  of installs (OV).

## Annual rotation

Add a calendar reminder ~30 days before each cert expires.
Cycle:

- Apple Developer Program: yearly.
- Sectigo / DigiCert OV: 1-year cycle.
- Sectigo / DigiCert EV: typically 1- or 3-year cycles
  depending on the issuance terms.

When a cert lapses, releases keep building (the conditional
step skips) but ship unsigned until the new cert lands. The
README and About dialog should call this out so users know
why their next install needs a Gatekeeper override.
