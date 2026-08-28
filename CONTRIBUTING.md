# Private source development

PrepMate source development is limited to authorized maintainers and
contributors in the private repository. Customer downloads are delivered
separately from the official website; this repository is not a public source
or contribution portal.

## Development rules

- Preserve the local-first data and provider boundary.
- Do not add accounts, hosted databases, billing, payments, telemetry, or
  automatic update checks without an explicit product decision.
- Provider keys and the local encryption key must remain in the operating-system
  keychain and never enter SQLite, browser storage, logs, or package contents.
- Candidate code must never execute without a verified macOS Seatbelt sandbox.
- Do not weaken transcript, report, Performance, or Improve evidence truth.
- Document every new network destination in `PRIVACY.md`.
- Add tests for schema, provider, security, lifecycle, packaging, and
  distribution changes.

Use focused reviewed changes and record the user-visible behavior and test
evidence. Apache-2.0 remains the project license. The private repository may
use its own internal review and sign-off policy.
