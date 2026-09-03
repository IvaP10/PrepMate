import type { Metadata } from "next";
import { siteConfig } from "@/lib/site-config";
import { InfoLayout } from "@/components/info-layout";
import { SiteLink } from "@/components/site-link";

export const metadata: Metadata = {
  title: "Support",
  description: "Support information for the local-first PrepMate macOS application.",
};

export const dynamic = "force-static";

export default function SupportPage() {
  return (
    <InfoLayout
      eyebrow="Support"
      title="Get unstuck, without sending your private practice."
      lede="PrepMate has no hosted support account or application-data inbox. Contact the support route with redacted, reproducible details."
    >
      <section className="prose-card">
        <h2>Contact support</h2>
        <p>Include your PrepMate version, Mac architecture, the visible error, and whether it happens in the packaged app or an authorized source-development checkout. Use synthetic resume and interview data whenever possible.</p>
        <a className="contact-link" href={"mailto:" + siteConfig.supportEmail}>{siteConfig.supportEmail} ↗</a>
        <h2>Keep these details private</h2>
        <p>Never attach API keys, resumes, transcripts, provider responses, database files, signing material, or unredacted local paths. Provider outages, provider retention, billing, and provider-account issues must be handled with the selected AI provider.</p>
        <h2>Before you write</h2>
        <p>Check the <SiteLink className="text-link" href="/download">download page</SiteLink> for the current release and the <SiteLink className="text-link" href="/privacy">privacy boundary</SiteLink> for what can leave the device.</p>
      </section>
    </InfoLayout>
  );
}
