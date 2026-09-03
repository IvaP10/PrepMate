import type { Metadata } from "next";
import { siteConfig } from "@/lib/site-config";
import { InfoLayout } from "@/components/info-layout";

export const metadata: Metadata = {
  title: "Security",
  description: "Security reporting and release trust information for PrepMate.",
};

export const dynamic = "force-static";

export default function SecurityPage() {
  return (
    <InfoLayout
      eyebrow="Security"
      title="Trust is part of the product."
      lede="The application is designed around a small local boundary: a loopback API, encrypted local data, OS-keychain secrets, and explicit provider traffic."
    >
      <section className="prose-card">
        <h2>Report a vulnerability privately</h2>
        <p>Do not publish a suspected vulnerability or include API keys, resumes, transcripts, databases, or provider responses. Use the private security route below with the affected version, platform, reproduction steps, and expected impact.</p>
        <a className="contact-link" href={"mailto:" + siteConfig.securityEmail}>{siteConfig.securityEmail} ↗</a>
        <h2>Release verification</h2>
        <p>When a macOS build is published, it is Developer ID signed, notarized, stapled, and checked on Apple Silicon and Intel Macs. Each release publishes SHA-256 checksums, SBOMs, and the applicable license and attribution notices.</p>
        <h2>Runtime invariants</h2>
        <p>The local API binds to loopback, validates its origin and per-launch token, and never writes provider or encryption keys to SQLite, browser storage, logs, or release artifacts. Technical code execution fails closed without macOS Seatbelt.</p>
      </section>
    </InfoLayout>
  );
}
