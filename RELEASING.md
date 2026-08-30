# Releasing PrepMate Desktop

PrepMate is distributed as a binary-only macOS application from the official
website. The source repository and CI remain private. This process never
creates a public source archive or GitHub Release.

The official website is the separate static `PrepMate-website` project. Netlify
hosts that project; Cloudflare R2 serves immutable release assets and the public
`latest.json` manifest. The website has no route to the desktop API.

## One-time private setup

Configure the final values in `PUBLICATION_METADATA.json`:

- final product name, slug, bundle identifier, and copyright owner;
- official website, download, manifest, support, and security URLs;
- immutable release-storage base URL;
- supported platforms: `macos-arm64` and `macos-x64`.

Set up the private CI environment `production-release` with required
reviewers. Store signing material only in the CI secret store:

- `MACOS_CSC_LINK`
- `MACOS_CSC_KEY_PASSWORD`
- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`
- `APPLE_TEAM_ID`
- `R2_ENDPOINT`
- `R2_BUCKET`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

The R2 bucket should expose only the public release prefix through an HTTPS
custom download hostname. Keep versioned release objects immutable. The
website reads the public `latest.json` manifest and does not receive private
repository credentials.

For local unsigned packaging, run:

```bash
npm run package:mac
```

The signed/notarized macOS release command is:

```bash
npm run release:macos
```

The latter requires the completed binary-distribution metadata and these local
Apple signing variables: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`,
`APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID`. In private CI, the
`MACOS_*` secrets are mapped to those variables. It produces both DMG and ZIP
targets; the private CI workflow adds the checksum, SBOM, notice, release
notes, manifest, and approval gates before any public upload.

## Prepare a version

1. Update the same semantic version in `package.json`,
   `Frontend/package.json`, and `desktop/package.json`, then refresh all
   package locks.
2. Update the changelog, capability table, privacy disclosures, and third-party
   notices when behavior or dependencies change.
3. Run the complete source, security, dependency, SQLite, frontend, and
   desktop-bundle validation locally.
4. Build both macOS architectures from a clean private checkout.
5. Create a signed version tag in the private repository.

Tags start the validation and packaging workflow. A manual reviewer approval
for the `production-release` environment is required before the workflow can
upload anything to public storage.

## Release workflow

The workflow:

1. Validates the private source boundary and metadata.
2. Builds the standalone frontend and frozen backend.
3. Builds Apple Silicon and Intel DMG/ZIP artifacts on native macOS runners.
4. Signs with Developer ID, notarizes, staples, and verifies each application.
5. Generates checksums, SBOMs, license inventory, versioned release notes, and
   the public download manifest.
6. Copies `LICENSE`, `NOTICE`, `PRIVACY.md`, `RELEASE_NOTES.md`, and
   `THIRD_PARTY_NOTICES.md` beside the release assets.
7. Uploads immutable versioned files to the release bucket.
8. Publishes `latest.json` last, so an incomplete release cannot become the
   current public version.

The workflow does not upload source code, create a GitHub Release, or expose
the private repository URL to customers.

## Required acceptance

Before approving publication:

- `python scripts/release_checks.py --distribution --tag v<version>` passes.
- Both artifacts pass `codesign --verify --deep --strict`.
- Both applications pass `xcrun stapler validate` and `spctl --assess`.
- Both DMGs pass `hdiutil verify`.
- A clean Apple Silicon Mac and a clean Intel Mac can install and launch the
  application without Python, Node.js, or repository files.
- Settings works with a configured provider and persists the key in the
  operating-system keychain.
- No provider request occurs before explicit provider setup.
- Interview, resume import, reports, Performance, Improve, export, deletion,
  complete wipe, and macOS Seatbelt technical execution are exercised.
- Every public manifest checksum matches the uploaded artifact.
- The public Download page links only to the approved versioned assets.

Unsigned local DMGs remain development artifacts and must never be linked from
the public website.

## Future Windows release

Windows remains excluded from the public distribution until Windows Credential
Manager storage, secure technical execution, native packaging, Authenticode
signing, and clean-machine testing are complete.
