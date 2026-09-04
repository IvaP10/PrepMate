# PrepMate download site

This is the public information and download site for the private-source
PrepMate desktop application. It contains no application backend, account
system, provider credentials, analytics, or customer data.

The current `public/latest.json` exposes the Apple Silicon alpha DMG through
the public GitHub repository. It is ad-hoc signed and not notarized; replace
this manifest with the verified release manifest before distributing a
production build. Configure these public values in the hosting environment:

- NEXT_PUBLIC_PREPMATE_RELEASE_MANIFEST_URL
- NEXT_PUBLIC_PREPMATE_SUPPORT_EMAIL
- NEXT_PUBLIC_PREPMATE_SECURITY_EMAIL

The release workflow publishes the immutable installers, generated release
notes, verification files, and a latest.json manifest to the download storage
hostname. The website reads that manifest and shows download buttons and
verification links only for HTTPS artifacts from a published manifest.
