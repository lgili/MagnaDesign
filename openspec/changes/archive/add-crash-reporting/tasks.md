# Tasks — add-crash-reporting

## Phase 1 — Sentry crash reporter

- [ ] Add `sentry-sdk` to `pyproject.toml` deps (or
      `[telemetry]` extra if we want it optional).
- [ ] Create a Sentry project at sentry.io, generate a public DSN,
      store as a non-secret build constant in
      `pfc_inductor/telemetry/_dsn.py` (DSN is safe to ship).
- [ ] `pfc_inductor/telemetry/crashes.py`:
      - `init_crash_reporter(consent: bool, env: str = "prod")`.
      - Configure `before_send` hook to scrub filesystem paths,
        email-shaped strings, project file contents.
      - Tag every event with `app_version`, `git_sha`, `qt_version`,
        `python_version`, `os`, `arch`.
- [ ] `__main__.py` calls `init_crash_reporter(consent_from_qsettings())`
      after `QApplication` is built but before any other code.
- [ ] Skip on offscreen / CI: check
      `QGuiApplication.platformName() in ("offscreen", "minimal")`
      and `os.environ.get("MAGNADESIGN_DISABLE_TELEMETRY")`.

## Phase 2 — Consent UX

- [ ] First-run consent dialog (`ui/widgets/consent_dialog.py`):
      title "Help us improve MagnaDesign", body explaining the
      data collected, three buttons:
      "Send crash reports" / "No thanks" / "Customise…".
- [ ] "Customise…" opens Settings → Privacy with the two granular
      toggles (Crash reports / Usage analytics).
- [ ] Choice saved to `QSettings("telemetry/consent")` as a JSON
      object so we can extend without losing prior answers.
- [ ] Settings page: a top "Privacy" section with the two toggles
      and a "Privacy policy →" link button opening `docs/privacy.md`.

## Phase 3 — Scrubbing

- [ ] `crashes.py:scrub_event(event)`:
      - Replace any path under the user's home with `~/...`.
      - Drop file-content-looking strings (size > 200 chars).
      - Drop any breadcrumbs whose category is `project_file`.
      - Drop QSettings values that match `*_path|*_name|user/*`.
- [ ] Test: `tests/test_telemetry_scrub.py` with a synthetic
      event carrying every redactable field; assert post-scrub
      it's clean.

## Phase 4 — Optional analytics

- [ ] `pfc_inductor/telemetry/analytics.py`:
      - `track_event(name, properties=None)` posts to a PostHog
        endpoint with `disable_geoip=True`. No-op if consent off.
      - Use PostHog's `distinct_id` = a random UUID stored in
        `QSettings`, never PII.
- [ ] Wire `track_event` calls at the 6 milestones listed in the
      proposal. Each call lives in 1 line at the relevant slot.

## Phase 5 — Docs + release

- [ ] `docs/privacy.md`: data dictionary, what's collected, what's
      not, retention policy, opt-out mechanism, contact for data
      deletion requests (per GDPR Art. 17).
- [ ] About dialog gets a "Privacy policy" link and an inline
      "Telemetry: enabled / disabled" status line.
- [ ] CHANGELOG mentions the consent flow.
- [ ] CI runs the consent-disabled path in offscreen mode to
      verify no Sentry / PostHog network calls happen.
