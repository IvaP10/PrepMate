# PrepMate

PrepMate is a local-first desktop app for practicing behavioral and technical
interviews. It uses your resume, job description, and selected interview
profile to run an interview and produce an evidence-backed report.

PrepMate runs as a native Electron app. The API, database, and renderer run on
your computer. There is no PrepMate account or hosted PrepMate backend.

## Current status

- macOS 13 Ventura or later
- The checked-in app build is for Apple Silicon Macs (`arm64`)
- The current DMG is an unsigned internal alpha build
- There is no signed, notarized public release or GitHub Release yet
- Windows and Linux installers are not currently distributed

## Download the current app

The current DMG is stored in Git LFS in this private repository. You need
repository access, macOS on Apple Silicon, and Git LFS.

```bash
git lfs install
git clone https://github.com/IvaP10/PrepMate.git
cd PrepMate
git lfs pull --include="desktop/release/*.dmg"
open desktop/release/PrepMate-0.1.0-alpha.1-mac-arm64.dmg
```

When the disk image opens:

1. Drag `PrepMate.app` to `Applications`.
2. Open it from Applications.

The current DMG is unsigned. macOS may show a security warning. Only open it
if you trust the repository and the build.

## Run from source

### Requirements

- macOS 13 or later
- Python 3.12 or 3.13
- Node.js 22 or later
- npm

### Install dependencies

Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
npm ci --prefix Frontend
npm ci --prefix desktop
```

### Start PrepMate

Run the Electron app with:

```bash
cd Frontend
npm run dev
```

This starts the local API and the Next.js renderer, then opens the app in
Electron. Do not open the renderer URL directly in a normal browser.

### First launch

1. Open **Settings**.
2. Select an AI provider and model.
3. Enter an API key if the provider requires one.
4. Save the settings.
5. Add your resume and job description, then start an interview.

AI-assisted features require a configured provider. Provider keys are stored
in the operating-system keychain.

## Build a macOS package

Install the build dependencies first:

```bash
python -m pip install -r requirements-build.txt
```

Build an Apple Silicon DMG and ZIP from the repository root:

```bash
npm run package:mac
```

The files are written to `desktop/release/`. Local builds are unsigned and are
for development only.

To build an Intel package on an Intel Mac:

```bash
PREPMATE_MAC_ARCH=x64 npm run package:mac
```

## Data and privacy

PrepMate stores the local database, interview history, resumes, job
descriptions, reports, Performance data, and Improve data in the Electron
application-data directory:

```text
~/Library/Application Support/PrepMate
```

When an AI feature is used, the provider selected in Settings receives the
context required for that feature. PrepMate does not operate a hosted API or
analytics service.

See [PRIVACY.md](PRIVACY.md) for data export, deletion, provider, and keychain
details.

## Repository layout

- `Frontend/` — Electron renderer
- `desktop/` — Electron entry point and packaging configuration
- Root Python files — local FastAPI API and application workflows
- `local_migrations/` — SQLite migration history
- `tests/` — automated tests
- `scripts/` — validation and release scripts

## Useful commands

```bash
# Start the desktop app
cd Frontend && npm run dev

# Run Python tests and frontend tests
npm test

# Run frontend type checking
npm run typecheck

# Run source and release checks
npm run release:check
```

## License

PrepMate is licensed under the [Apache License 2.0](LICENSE). See
[`NOTICE`](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for
attribution information.
