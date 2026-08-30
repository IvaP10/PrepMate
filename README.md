# PrepMate Desktop

PrepMate is a local-first desktop interview coach for interview practice,
technical rounds, evidence-backed reports, Performance history, and Improve
coaching. This private repository contains the application source and one
Apple Silicon development DMG stored with Git LFS. A signed and notarized
customer release has not been published yet.

There are no PrepMate accounts, subscriptions, payments, hosted databases,
analytics, or PrepMate application servers.

## Current release status

`desktop/release/PrepMate-0.1.0-alpha.1-mac-arm64.dmg` is an unsigned internal
development artifact. It has no Apple notarization ticket and must not be
advertised as a public or production-ready download.

The private release workflow is prepared to build Apple Silicon and Intel
assets, but customer distribution remains blocked until the owner, website,
storage, signing, notarization, and clean-machine gates in
[`PUBLIC_RELEASE_BLOCKERS.md`](PUBLIC_RELEASE_BLOCKERS.md) are complete. An
approved release must include release notes, SHA-256 checksums, SBOMs, and the
required license and attribution notices.

The source repository and customer downloads are separate. No source code,
source archive, or GitHub Release is required to download or use PrepMate.

On first launch, open **Settings**, select a provider and model, enter its API
key when required, and save. Settings probes the candidate configuration before
committing it. A loopback OpenAI-compatible endpoint may be keyless. API keys
and the local field-encryption key are stored in the operating-system keychain
and are never returned to the renderer.

## Capabilities

| Capability | Status |
| --- | --- |
| Typed behavioral interviews, reports, Performance, Improve | Available with a configured text provider |
| Voice answers | Available only when the selected provider supports transcription |
| Selectable PDF and DOCX resume import | Available in the core install |
| Scanned-PDF OCR | Optional heavyweight source-install pack |
| Interviewer speech | Not included; questions remain readable text |
| Technical questions without execution | Available |
| Sandboxed code execution | Available on macOS when Seatbelt and the selected language runtime are detected |
| macOS installer | Unsigned Apple Silicon development DMG available; signed/notarized Apple Silicon and Intel releases pending |
| Windows installer | Not released until secure execution and native packaging are verified |
| Linux installer | Not released in this distribution |

Camera and screen sharing are optional coaching controls and are never required
for a score or report. The app has no automatic updater; after distribution is
approved, users will return to the official channel to install newer versions.

## Local-first architecture

```text
PrepMate desktop -> loopback API -> encrypted SQLite fields
                              -> OS keychain -> selected AI provider
```

Before provider setup, the app makes only loopback requests to its own local
services. After setup, prompts and the minimum context needed for an AI feature
go directly to the provider selected in Settings.

The API and renderer bind only to loopback. Both require random per-launch
desktop tokens, so the renderer is not a standalone website and ordinary
browser access is rejected. Sensitive database fields use AES-GCM with
a separate key held in the OS keychain. Technical submissions execute only
through a supported macOS Seatbelt sandbox and fail closed when it is
unavailable.

## Repository layout

- `Frontend/` — the private Next.js renderer used only inside Electron.
- `desktop/` — Electron startup, packaging configuration, entitlements, and
  the Git LFS development DMG.
- Root Python modules — the loopback FastAPI service and interview, technical,
  report, Performance, and Improve workflows.
- `local_migrations/` and `local_schema.sql` — immutable SQLite schema history
  and the current local schema.
- `scripts/` — source-boundary, release, license, migration, and bundle checks.
- `tests/` — regression coverage; tests are not bundled into the customer app.

## Local data

The SQLite database, preferences, resumes, job descriptions, saved roles,
interview history, reports, Performance evidence, and Improve data live under
Electron's application-data directory:

- macOS: `~/Library/Application Support/PrepMate`

When the backend is run directly from the private source checkout, set
`PREPMATE_DATA_DIR` only when a different local directory is required. The old
`INTERAI_DATA_DIR` variable remains accepted for private migration scripts.

## Development

Source development requires Python 3.12 or 3.13 and Node.js 22+:

```bash
python3 -m pip install -r requirements.lock.txt
npm ci --prefix Frontend
npm ci --prefix desktop
```

The internal DMG is stored with Git LFS. Developers who need that artifact can
retrieve it with:

```bash
git lfs install
git lfs pull --include='desktop/release/*.dmg'
```

Launch the complete desktop application from either the repository root or the
renderer directory:

```bash
npm run dev
# or
cd Frontend && npm run dev
```

The command starts the private loopback API and renderer, then opens PrepMate in
Electron. Do not open the loopback renderer in a browser; it deliberately
rejects non-Electron requests.

## Desktop packaging

The Electron wrapper, PyInstaller backend, and macOS installer targets are in
`desktop/`. From the private repository root:

```bash
# Apple Silicon DMG/ZIP
npm run package:mac

# Intel DMG/ZIP on an Intel macOS build host
PREPMATE_MAC_ARCH=x64 npm run package:mac
```

The local output is written to `desktop/release/`. Unsigned local builds are
for development only. The public release workflow uses Apple Developer ID
signing, notarization, stapling, checksum generation, SBOM generation, and
clean-machine verification before uploading assets to the official download
storage.

See [RELEASING.md](RELEASING.md) and [PUBLIC_RELEASE_BLOCKERS.md](PUBLIC_RELEASE_BLOCKERS.md)
for the private-repository release process and binary publication gates.

## Privacy and network boundary

PrepMate does not send application data to a PrepMate-operated server. When an
AI feature is used, the selected provider may receive resume-derived context,
job descriptions, interview questions and answers, transcript excerpts,
technical reasoning, and report or coaching inputs. Review the selected
provider's retention terms before sending sensitive material.

Camera coaching is processed in the renderer and does not download a vision
model or upload camera frames. The app does not download speech or vision
models and does not include interviewer text-to-speech.

Read [PRIVACY.md](PRIVACY.md) for deletion, export, keychain, provider, and
local code-execution details.

## License and notices

PrepMate remains licensed under the [Apache License 2.0](LICENSE). Approved
binary downloads must include `LICENSE`, `NOTICE`, and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). The source repository is
private, but the Apache-2.0 license and applicable attribution obligations
remain in force for distributed binaries.
