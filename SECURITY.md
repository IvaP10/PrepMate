# Security policy

## Reporting a vulnerability

Use the public security route listed on the official PrepMate website.
It must be a private, nonpersonal route configured in
`PUBLICATION_METADATA.json`; do not open a public issue or include real API
keys, resumes, transcripts, local database files, or provider responses.

Include the affected version, platform, reproduction steps, expected impact,
and whether the issue can expose keychain credentials, local files, provider
prompts, or candidate-code execution. Use synthetic data only.

The maintainer will acknowledge a complete report as soon as practical,
coordinate a fix and disclosure date, and credit the reporter unless anonymity
is requested. Public disclosure should wait until a patched release exists.

## Supported versions

Only the latest signed and notarized macOS download listed on the official
website is supported. Unsigned development artifacts and private source
checkouts are not supported release builds.

## Release security invariants

- The API binds only to loopback and validates Host, Origin, and the packaged
  per-launch token.
- API and data-encryption keys never enter SQLite, settings JSON, renderer
  storage, package contents, logs, crash reports, or release artifacts.
- Candidate code execution fails closed without the macOS Seatbelt sandbox.
- Public macOS artifacts are Developer ID signed, notarized, and stapled.
- Public release assets include SHA-256 checksums and an SBOM.
- The public website does not collect provider keys or application data.
