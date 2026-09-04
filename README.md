# PrepMate

PrepMate is a local-first desktop app for practicing behavioral and technical
interviews. It uses your resume, job description, and selected interview
profile to run an interview and produce an evidence-backed report.

The app runs in Electron. Your data is stored locally on your computer. There
is no PrepMate account or hosted PrepMate backend.

## Repository boundaries

This repository contains the private desktop product: the Electron shell, local
API, local SQLite storage, and the in-app renderer in `Frontend/`. It also
contains the public marketing site in `website/`; the GitHub Pages workflow
deploys that directory to `https://ivap10.github.io/PrepMate/`.

The `website/` project is static and contains product information, legal pages,
support, and approved macOS download links. It never connects to the desktop
API or receives application data. The site reads a public release manifest; the
release process keeps that manifest pending until a signed and notarized build
is ready.

The separate `PrepMate-website` repository is not the source for this
project-site URL. Changes made only there do not trigger the `PrepMate` Pages
workflow; update `website/` in this repository and push `main` when publishing
the site.

## Download and install the app

The current download is an unsigned Apple Silicon macOS alpha build. A signed
and notarized public release is not available yet.

The DMG is stored in Git LFS in this private repository. You need:

- access to this GitHub repository;
- macOS 13 Ventura or later;
- an Apple Silicon Mac; and
- Git LFS installed.

### 1. Download the DMG

Run these commands in Terminal:

```bash
git lfs install
git clone https://github.com/IvaP10/PrepMate.git
cd PrepMate
git lfs pull --include="desktop/release/*.dmg"
open desktop/release/PrepMate-0.1.0-alpha.1-mac-arm64.dmg
```

If `git lfs` is not installed, install Git LFS first and run `git lfs install`
again.

### 2. Install PrepMate

When the DMG opens:

1. Drag `PrepMate.app` to the `Applications` folder.
2. Open `PrepMate` from `Applications`.

The current DMG is unsigned, so macOS may show a security warning. Only open
it if you trust the repository and the build.

You do not need Python, Node.js, or the source code to run the downloaded app.

## Set up the app

PrepMate needs either an API key for a supported provider or a running local
OpenAI-compatible server.

1. Open PrepMate and go to **Settings**.
2. Choose a provider:
   - **OpenAI**
   - **Anthropic**
   - **Google Gemini**
   - **OpenAI-compatible endpoint**
3. Enter the exact model name accepted by that provider.
4. Choose one of the setup options below.
5. Click **Test and save**.

### Use a provider API key

For OpenAI, Anthropic, or Google Gemini:

1. Select the provider.
2. Enter the model name.
3. Paste the provider API key into **API key**.
4. Click **Test and save**.
5. Approve secure storage access if macOS asks.

PrepMate stores the key in the operating-system keychain. It is not stored in
the app database or browser storage.

### Use a local host

To use a local model server that exposes an OpenAI-compatible API:

1. Select **OpenAI-compatible endpoint**.
2. Enter the exact local model name.
3. Enter the server base URL, for example:
   `http://localhost:11434/v1`.
4. Leave **API key** blank when the server is on `localhost`, `127.0.0.1`, or
   `::1` and does not require a key.
5. Click **Test and save**.

The local server must already be running and must support the OpenAI-compatible
chat completions API. If it requires authentication, enter its API key.

Voice transcription currently requires OpenAI. Typed answers work with any
configured provider that supports text generation.

## Use PrepMate

1. Add or import your resume.
2. Add the job description for the role you are preparing for.
3. Select an interview profile: **Top Tier**, **Mid Tier**, **Startup**, or
   **Custom**.
4. Start the interview.
5. Answer each question by typing or using your microphone.
6. Complete the interview to generate the report.
7. Review the report, Performance history, and Improve coaching.

The resume and job description personalize the interview. The selected profile
controls the interview style, difficulty, timing, and depth.

## GitHub source and developer setup

The downloaded DMG is the easiest way to run PrepMate. Use the source setup
below only when developing or building the app.

### Requirements

- macOS 13 or later
- Python 3.12 or 3.13
- Node.js 22 or later
- npm

### Download the source

```bash
git clone https://github.com/IvaP10/PrepMate.git
cd PrepMate
```

### Install dependencies

Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
npm ci --prefix Frontend
npm ci --prefix desktop
```

### Run from source

Start the full desktop app through Electron:

```bash
cd Frontend
npm run dev
```

This starts the local API and renderer, then opens PrepMate in Electron. Do
not open the renderer URL directly in a normal browser.

## Build a macOS package

After completing the source setup, open a new Terminal window and go to the
repository root. Install the build dependencies:

```bash
cd /path/to/PrepMate
python -m pip install -r requirements-build.txt
```

Build an Apple Silicon DMG and ZIP:

```bash
cd /path/to/PrepMate
npm run package:mac
```

The output is written to `desktop/release/`. Local packages are unsigned and
are for development only.

Build an Intel package on an Intel Mac:

```bash
cd /path/to/PrepMate
PREPMATE_MAC_ARCH=x64 npm run package:mac
```

## Useful commands

```bash
# Run frontend type checking
npm run typecheck

# Run source and release checks
npm run release:check
```

## Local data

PrepMate stores its local database, resumes, job descriptions, interview
history, reports, Performance data, and Improve data here on macOS:

```text
~/Library/Application Support/PrepMate
```

See [PRIVACY.md](PRIVACY.md) for data export, deletion, provider, and keychain
details.

## License

PrepMate is licensed under the [Apache License 2.0](LICENSE). See
[`NOTICE`](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for
attribution information.
