import type { Metadata } from "next";
import { InfoLayout } from "@/components/info-layout";

export const metadata: Metadata = {
  title: "Privacy",
  description: "How PrepMate handles local data and explicit provider requests.",
};

export const dynamic = "force-static";

export default function PrivacyPage() {
  return (
    <InfoLayout
      title="Your practice stays yours."
      lede="PrepMate is a local-first macOS app. It does not require a PrepMate account or send application data to a PrepMate-operated server."
    >
      <section className="prose-card">
        <h2>What stays on your Mac</h2>
        <p>Preferences, resumes, job descriptions, interview state, transcripts, technical attempts, reports, Performance evidence, and Improve progress are stored in the local application-data directory. Sensitive fields are encrypted with AES-GCM. The encryption key and provider API keys are held separately in the operating-system keychain.</p>
        <h2>What can leave your Mac</h2>
        <p>When you use an AI feature, PrepMate sends the minimum prompt context needed for that feature directly to the provider selected in Settings. This can include resume-derived context, job descriptions, interview questions and answers, transcript excerpts, technical reasoning, and report or coaching inputs. Review the provider&apos;s retention terms before sending sensitive material.</p>
        <h2>Before provider setup</h2>
        <p>Before you configure a provider, the app communicates only with its own loopback desktop services. There is no analytics, advertising, telemetry, automatic update check, or hosted application request.</p>
        <h2>Camera and technical practice</h2>
        <p>Camera, microphone, and screen coaching are optional and start only after you choose them. Camera coaching is processed in the renderer and camera frames are not uploaded by PrepMate. Technical code executes only through the macOS Seatbelt sandbox and is disabled when the sandbox is unavailable.</p>
        <h2>Export and deletion</h2>
        <p>Settings provides export, deletion, cache clearing, provider-key removal, local-data-folder access, and complete wipe controls. Exports are readable JSON and are not encrypted after export. Uninstall preserves application data by default; use complete wipe when you want a full reset.</p>
      </section>
    </InfoLayout>
  );
}
