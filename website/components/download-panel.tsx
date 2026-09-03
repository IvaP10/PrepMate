"use client";

import { useEffect, useState } from "react";
import { siteConfig } from "@/lib/site-config";

type Artifact = {
  filename: string;
  url: string;
  sha256: string;
  size_bytes?: number;
};

type DownloadManifest = {
  schema?: string;
  status?: string;
  product_name?: string;
  version?: string;
  channel?: string;
  released_at?: string;
  supported_macos_versions?: string[];
  known_limitations?: string[];
  downloads?: {
    macos?: {
      arm64?: { dmg?: Artifact; zip?: Artifact };
      x64?: { dmg?: Artifact; zip?: Artifact };
    };
  };
  verification?: {
    checksums?: string;
    sbom?: string[];
    license_inventory?: string;
  };
  release_notes_url?: string;
  legal?: {
    license?: string;
    notice?: string;
    privacy?: string;
    third_party_notices?: string;
  };
};

function safeHttpsUrl(value: string | undefined) {
  if (!value) return null;
  try {
    const pathValue =
      value.startsWith("/") && !value.startsWith("//")
        ? siteConfig.publicPath(value)
        : value;
    const url = new URL(pathValue, window.location.origin);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function formatSize(bytes?: number) {
  if (!bytes || !Number.isFinite(bytes)) return "";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function formatReleaseDate(value?: string) {
  if (!value) return "Shown when published";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Shown when published";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

function ReleaseCard({
  title,
  detail,
  artifact,
}: {
  title: string;
  detail: string;
  artifact?: { dmg?: Artifact; zip?: Artifact };
}) {
  const dmgUrl = safeHttpsUrl(artifact?.dmg?.url);
  const zipUrl = safeHttpsUrl(artifact?.zip?.url);
  const ready = Boolean(dmgUrl && zipUrl);
  const size = formatSize(artifact?.dmg?.size_bytes);
  return (
    <article className="release-card">
      <div className="release-card-top">
        <div>
          <span className="release-platform">{title}</span>
          <p>{detail}</p>
        </div>
        <span className={"release-state" + (ready ? " ready" : "")}>
          <span aria-hidden="true" /> {ready ? "Ready" : "Pending"}
        </span>
      </div>
      <div className="release-actions">
        {dmgUrl ? (
          <a className="button button-primary" href={dmgUrl} download>
            Download DMG <span aria-hidden="true">↓</span>
          </a>
        ) : (
          <span className="button button-disabled" aria-disabled="true">DMG pending</span>
        )}
        {zipUrl ? (
          <a className="button button-quiet" href={zipUrl} download>ZIP</a>
        ) : (
          <span className="button button-quiet button-disabled" aria-disabled="true">ZIP pending</span>
        )}
      </div>
      {artifact?.dmg ? (
        <p className="checksum">
          SHA-256: <code>{artifact.dmg.sha256}</code>{size ? " · " + size : ""}
        </p>
      ) : null}
    </article>
  );
}

export function DownloadPanel() {
  const [manifest, setManifest] = useState<DownloadManifest | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "pending">("loading");

  useEffect(() => {
    let active = true;
    fetch(siteConfig.manifestUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("manifest unavailable");
        return response.json() as Promise<DownloadManifest>;
      })
      .then((value) => {
        if (!active) return;
        const valid = value?.schema === "prepmate-download-manifest-v1";
        setManifest(valid ? value : null);
        setLoadState(valid && value.status === "published" ? "ready" : "pending");
      })
      .catch(() => {
        if (active) setLoadState("pending");
      });
    return () => {
      active = false;
    };
  }, []);

  const macos = manifest?.downloads?.macos;
  const version = manifest?.version || "0.1.0-alpha.1";
  const supportedMacos = manifest?.supported_macos_versions?.length
    ? manifest.supported_macos_versions
    : ["macOS 13 Ventura and later"];
  const limitations = manifest?.known_limitations?.length
    ? manifest.known_limitations
    : [
        "Alpha release; configure a supported AI provider for AI-assisted features.",
        "Technical execution requires macOS Seatbelt and a supported language runtime.",
        "Updates are installed manually from the official Download page.",
      ];
  const resourceLinks = [
    { label: "Latest manifest", url: safeHttpsUrl(siteConfig.manifestUrl) },
    { label: "Release notes", url: safeHttpsUrl(manifest?.release_notes_url) },
    { label: "SHA-256 checksums", url: safeHttpsUrl(manifest?.verification?.checksums) },
    ...(manifest?.verification?.sbom || []).map((url, index) => ({
      label: `SBOM ${index + 1}`,
      url: safeHttpsUrl(url),
    })),
    {
      label: "License inventory",
      url: safeHttpsUrl(manifest?.verification?.license_inventory),
    },
    { label: "LICENSE", url: safeHttpsUrl(manifest?.legal?.license) },
    { label: "NOTICE", url: safeHttpsUrl(manifest?.legal?.notice) },
    {
      label: "Third-party notices",
      url: safeHttpsUrl(manifest?.legal?.third_party_notices),
    },
  ].filter((resource): resource is { label: string; url: string } => Boolean(resource.url));
  return (
    <section className="download-panel" aria-labelledby="download-options">
      <div className="download-panel-heading">
        <div>
          <span className="eyebrow">Current release</span>
          <h2 id="download-options">
            {loadState === "ready"
              ? (manifest?.product_name || siteConfig.productName) + " " + version
              : "macOS builds · " + version}
          </h2>
        </div>
        <span className="channel-badge">
          {loadState === "ready" ? manifest?.channel || "release" : "Release pending"}
        </span>
      </div>
      <p className="download-panel-copy">
        {loadState === "ready"
          ? "Choose the build that matches your Mac. The installer is signed and notarized before it appears here."
          : "The public release manifest is not connected yet. Signed downloads will appear here after the release gates pass."}
      </p>
      <div className="release-grid">
        <ReleaseCard title="Apple Silicon" detail="M-series Macs · arm64" artifact={macos?.arm64} />
        <ReleaseCard title="Intel" detail="Intel Macs · x64" artifact={macos?.x64} />
      </div>
      <div className="release-meta" aria-label="Release details">
        <div><span>Version</span><strong>{version}</strong></div>
        <div><span>Release date</span><strong>{formatReleaseDate(manifest?.released_at)}</strong></div>
        <div><span>Supported macOS</span><strong>{supportedMacos.join(", ")}</strong></div>
      </div>
      <div className="release-limitations">
        <span className="section-label">Known limitations</span>
        <ul className="limitations-list">
          {limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
        </ul>
      </div>
      {resourceLinks.length ? (
        <div className="verification-resources">
          <span className="section-label">Release files</span>
          <div className="verification-links">
            {resourceLinks.map((resource) => (
              <a className="verification-link" href={resource.url} key={resource.url}>
                {resource.label} ↗
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
