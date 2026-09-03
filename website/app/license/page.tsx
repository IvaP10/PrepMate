import type { Metadata } from "next";
import { InfoLayout } from "@/components/info-layout";
import { siteConfig } from "@/lib/site-config";

export const metadata: Metadata = {
  title: "License and notices",
  description: "Apache-2.0 licensing and third-party notices for PrepMate.",
};

export const dynamic = "force-static";

export default function LicensePage() {
  return (
    <InfoLayout
      eyebrow="License and notices"
      title="Open licensing, private source."
      lede="The source repository is private, but distributed PrepMate binaries remain under Apache-2.0 and include the applicable attribution materials."
    >
      <section className="prose-card">
        <h2>Apache License 2.0</h2>
        <p>PrepMate is distributed under the Apache License, Version 2.0. The license grants rights and states the conditions that apply to redistribution of the work in source or object form.</p>
        <div className="resource-links">
          <a className="resource-link" href={siteConfig.publicPath("/LICENSE")}>Read LICENSE <span>↗</span></a>
          <a className="resource-link" href={siteConfig.publicPath("/NOTICE")}>Read NOTICE <span>↗</span></a>
          <a className="resource-link" href={siteConfig.publicPath("/THIRD_PARTY_NOTICES.md")}>Read third-party notices <span>↗</span></a>
        </div>
        <h2>Release inventories</h2>
        <p>Each published version includes a dependency SBOM and license inventory beside its installers. Those version-specific inventories are the authoritative record for that release.</p>
      </section>
    </InfoLayout>
  );
}
