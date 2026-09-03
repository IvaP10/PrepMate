import type { Metadata } from "next";
import { DownloadPanel } from "@/components/download-panel";
import { InfoLayout } from "@/components/info-layout";
import { SiteLink } from "@/components/site-link";

export const metadata: Metadata = {
  title: "Download",
  description: "Download the official signed and notarized PrepMate macOS application.",
};

export const dynamic = "force-static";

export default function DownloadPage() {
  return (
    <InfoLayout
      eyebrow="The desktop app"
      title="A better practice loop, on your Mac."
      lede="Download the signed macOS build that matches your machine. PrepMate opens without an account; connect your own AI provider only when you are ready."
    >
      <DownloadPanel />
      <section className="content-section">
        <p className="section-label">Install in three steps</p>
        <div className="steps-grid">
          <article><span>01</span><h2>Choose your build</h2><p>Apple Silicon is for M-series Macs. Intel is for older Intel Macs. If you are unsure, choose Apple menu → About This Mac.</p></article>
          <article><span>02</span><h2>Move to Applications</h2><p>Open the DMG, drag PrepMate to Applications, then open it. The public build is signed and notarized for macOS.</p></article>
          <article><span>03</span><h2>Bring your provider</h2><p>Open Settings, select a provider and model, and enter your own API key when required. No PrepMate account is needed.</p></article>
        </div>
      </section>
      <section className="notice-card">
        <span className="notice-icon" aria-hidden="true">i</span>
        <div><strong>Local first, explicit by design.</strong><p>Resumes, answers, reports, Performance, and Improve data stay on your Mac. AI prompts go directly to the provider you choose.</p></div>
      </section>
      <section className="content-section availability-section">
        <p className="section-label">Availability</p>
        <h2>macOS is available now.</h2>
        <p>Windows and Linux downloads are not published yet. Windows will be released only after secure technical execution, native keychain storage, installer signing, and clean-machine verification are complete. The published manifest above is the source of truth for the current macOS version, release date, and support range.</p>
        <SiteLink className="text-link" href="/privacy">Read the privacy boundary ↗</SiteLink>
      </section>
    </InfoLayout>
  );
}
