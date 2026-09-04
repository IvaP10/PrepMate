"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { siteConfig } from "@/lib/site-config";

type ReleaseArtifact = {
  filename?: string;
  url?: string;
};

type DownloadManifest = {
  schema?: string;
  status?: string;
  downloads?: {
    macos?: {
      arm64?: { dmg?: ReleaseArtifact };
      x64?: { dmg?: ReleaseArtifact };
    };
  };
};

type MacDownload = {
  filename: string;
  url: string;
};

type MacArchitecture = "arm64" | "x64";

let macDownloadPromise: Promise<MacDownload | null> | null = null;

function safeDownloadUrl(value: string | undefined) {
  if (!value) return null;
  const pathValue =
    value.startsWith("/") && !value.startsWith("//")
      ? siteConfig.publicPath(value)
      : value;
  try {
    const url = new URL(
      pathValue,
      typeof window === "undefined" ? "https://prepmate.invalid" : window.location.origin,
    );
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function preferredArchitectures(): MacArchitecture[] {
  if (typeof navigator === "undefined") return ["arm64", "x64"];

  const browserNavigator = navigator as Navigator & {
    userAgentData?: { architecture?: string };
  };
  const reportedArchitecture = browserNavigator.userAgentData?.architecture || "";
  if (/arm|aarch/i.test(reportedArchitecture)) return ["arm64", "x64"];
  if (/x86|x64|amd/i.test(reportedArchitecture)) return ["x64", "arm64"];
  if (/arm64|aarch64/i.test(navigator.userAgent)) return ["arm64", "x64"];

  // Safari intentionally reports Apple Silicon Macs as Intel Macs. Prefer the
  // current arm64 release when the browser does not expose the architecture.
  return ["arm64", "x64"];
}

function loadMacDownload() {
  if (!macDownloadPromise) {
    macDownloadPromise = fetch(siteConfig.manifestUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("release manifest unavailable");
        return response.json() as Promise<DownloadManifest>;
      })
      .then((manifest) => {
        if (
          manifest?.schema !== "prepmate-download-manifest-v1" ||
          manifest.status !== "published"
        ) {
          return null;
        }

        const macos = manifest.downloads?.macos;
        for (const architecture of preferredArchitectures()) {
          const artifact = macos?.[architecture]?.dmg;
          const url = safeDownloadUrl(artifact?.url);
          if (url) {
            return {
              filename: artifact?.filename || "PrepMate-macOS.dmg",
              url,
            };
          }
        }
        return null;
      })
      .catch(() => null);
  }

  return macDownloadPromise;
}

function startDownload(download: MacDownload) {
  const link = document.createElement("a");
  link.href = download.url;
  link.download = download.filename;
  link.target = "_self";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function MacDownloadButton({
  className,
  children,
}: {
  className: string;
  children: ReactNode;
}) {
  const [download, setDownload] = useState<MacDownload | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let active = true;
    void loadMacDownload().then((value) => {
      if (!active) return;
      setDownload(value);
      setLoadState(value ? "ready" : "unavailable");
    });
    return () => {
      active = false;
    };
  }, []);

  function handleClick() {
    if (download) startDownload(download);
  }

  return (
    <button
      aria-busy={loadState === "loading"}
      className={className}
      disabled={loadState !== "ready"}
      onClick={handleClick}
      type="button"
    >
      {children}
    </button>
  );
}
