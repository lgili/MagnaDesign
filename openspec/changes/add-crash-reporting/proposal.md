# Add opt-in crash reporting (Sentry)

## Why

When the app crashes today, the only signal that reaches the
maintainers is "the app crashed" — no traceback, no user OS, no
spec that triggered it, no version. Bug reports degrade to
"sometimes the optimizer freezes" with no path to repro. For an
industrial tool that ships every couple of weeks across three
platforms, this is unworkable.

The minimum viable feedback loop is an **opt-in crash reporter**
that captures (a) the Python traceback, (b) the spec that was
loaded, (c) MagnaDesign version + commit SHA, (d) OS / Python /
Qt versions, (e) anonymised user ID for de-duplication. Sentry's
free tier (5 k events/month) covers a small team comfortably and
the SDK is one import.

A separate but related signal is **anonymous usage analytics** —
which features get used, how often, in what order. This is the
data product teams use to prioritise. It must be **strictly
opt-in** and disabled by default; a tool that phones home without
asking gets thrown out by every quality / IT team in the kind of
companies we want as users.

## What changes

Two distinct subsystems:

1. **Crash reporting** (`pfc_inductor/telemetry/crashes.py`):
   - Sentry SDK wired in `__main__.main()` with a public DSN.
   - First-run dialog: "Help us by sending crash reports?
     [Send] [Don't send]". Choice persisted in QSettings.
   - Per-event scrubbing: strip filesystem paths from breadcrumbs,
     redact email-shaped strings, never include the user's
     project file contents.
   - "Privacy policy" link in the About dialog leading to
     `docs/privacy.md` listing every field collected.
2. **Usage analytics** (`pfc_inductor/telemetry/analytics.py`):
   - Disabled by default. Settings → Privacy has a single
     "Send anonymous usage data" toggle.
   - Posts batched events to a privacy-respecting backend
     (PostHog self-hosted or Plausible) — no third-party
     tracking pixels.
   - Captures: app start, command-palette command run, optimizer
     run, datasheet exported, FEA validation run, error dialog
     shown. **Never**: spec values, project names, file paths.

## Impact

- **Dependency**: `sentry-sdk[pyside]` (~2 MB; MIT-licensed).
- **New module**: `pfc_inductor/telemetry/` (crashes + analytics).
- **No telemetry in CI / tests / offscreen mode** — guarded by
  `os.environ.get("MAGNADESIGN_TELEMETRY")` and the platform name
  check (skip on `offscreen` / `minimal`).
- **First-run UX**: an extra modal before the existing onboarding
  tour, asking the consent question. Skip on subsequent launches.
- **Privacy doc**: `docs/privacy.md` with the data dictionary.
- **Operational cost**: $0 on Sentry's free tier; Plausible self-
  hosted ~$5/mo on a tiny VPS, or skip analytics entirely.
- **Tests**: ~6 across `tests/test_telemetry_*` (consent gating,
  scrubbing, opt-out) using a Sentry mock transport.
- **Capability added**: `crash-reporting`, `usage-analytics`.
- **Effort**: ~3 days for crash reporting alone; +2 days if
  analytics ship together.
