# Binary release gates

PrepMate source remains private. A macOS binary may be advertised publicly
only after every gate below is complete.

## Owner-controlled gates

1. Select a cleared final product name and package-safe slug.
2. Configure an owned HTTPS website and download hostname.
3. Supply the exact legal copyright owner and create the final `NOTICE`.
4. Confirm rights for prompts, rubrics, questions, examples, icons, sounds, and
   every other project-authored or bundled asset.
5. Configure public support and security-report routes that do not expose
   private user data.
6. Configure immutable release storage and the public `latest.json` location.
7. Configure Apple Developer ID signing and Apple notarization credentials.
8. Complete clean Apple Silicon and Intel install and runtime verification.
9. Keep private-repository review and branch-protection checks enabled.

## Explicitly not required

- A public GitHub repository.
- A public source archive.
- A GitHub Release.
- Public GitHub Issues, Discussions, or security advisories.
- Public DCO identity or open-source contribution intake.
- A PrepMate account, payment system, licensing server, or telemetry service.

Record approved values in `PUBLICATION_METADATA.json`, set the status to
`approved_for_binary_distribution`, replace every `REQUIRED:` value, and run:

```bash
python scripts/release_checks.py --distribution --tag v<version>
```

That command must remain blocked while any branding, legal, signing, storage,
support, security, or clean-machine gate is incomplete.
