import type { Metadata } from "next";
import { InfoLayout } from "@/components/info-layout";

export const metadata: Metadata = {
  title: "Changelog",
  description: "PrepMate release notes and known limitations.",
};

export const dynamic = "force-static";

export default function ChangelogPage() {
  return (
    <InfoLayout
      eyebrow="Release notes"
      title="What changed."
      lede="PrepMate is in alpha. Release notes describe packaged behavior, privacy boundaries, and known limitations."
    >
      <section className="prose-card">
        <div className="release-heading"><span>0.1.0-alpha.1</span><small>Initial local-first release</small></div>
        <ul className="release-list">
          <li>Local SQLite history with OS-keychain provider credentials and encrypted sensitive fields.</li>
          <li>Behavioral interviews, technical rounds, evidence-backed reports, Performance, and Improve coaching.</li>
          <li>Optional camera and screen coaching with no punitive or pass/fail signals.</li>
          <li>Signed and notarized macOS Apple Silicon and Intel installers through the official Download page.</li>
          <li>No PrepMate account, hosted storage, billing, telemetry, or automatic updater.</li>
        </ul>
      </section>
    </InfoLayout>
  );
}
