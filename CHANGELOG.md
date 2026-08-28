# Changelog

All notable PrepMate changes are recorded here. The project is still an alpha,
so entries describe packaged behavior alongside known limitations.

## 0.1.0-alpha.1

- First local-first binary-distribution milestone with a reproducible macOS DMG path.
- Removed PrepMate accounts, hosted storage, billing, subscriptions, payments,
  credits, pricing, and telemetry.
- Added local SQLite storage, OS-keychain provider credentials, data export,
  selective deletion, cache clearing, and complete local wipe controls.
- Replaced the AGPL-only PDF dependency with `pypdfium2`.
- Made camera, screen, and self-review signals optional and non-punitive.
- Kept interviewer questions text-only after the optional local speech graph
  failed the release vulnerability policy; voice answers still use the
  explicitly selected transcription provider.
- Added Apache-2.0, privacy, security, private-development, release, and
  third-party notice documents.
- Added Apple Silicon and Intel macOS DMG/ZIP targets and a private CI
  packaging job; public binary distribution still requires owner-controlled
  signing, notarization, storage, and clean-machine checks.

Known alpha limitations are maintained in the README and release notes. The
fresh-database interview/report lifecycle passes in an isolated locked source
environment; the local DMG remains unsigned until release credentials are
configured.
