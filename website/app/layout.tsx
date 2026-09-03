import type { Metadata } from "next";
import { siteConfig } from "@/lib/site-config";
import "./globals.css";

const configuredSiteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.trim() || "http://localhost:3000";
const metadataBase = new URL(
  configuredSiteUrl.endsWith("/") ? configuredSiteUrl : `${configuredSiteUrl}/`,
);
const publicAssetUrl = (path: string) =>
  new URL(siteConfig.publicPath(path), `${metadataBase.origin}/`).toString();

export const dynamic = "force-static";

export const metadata: Metadata = {
  metadataBase,
  title: {
    default: "PrepMate · AI interview practice for macOS",
    template: "%s · PrepMate",
  },
  description:
    "Practice behavioral and technical interviews in a private macOS desktop app, then turn each answer into evidence and focused improvement.",
  applicationName: "PrepMate",
  icons: {
    icon: publicAssetUrl("/favicon.svg"),
  },
  openGraph: {
    type: "website",
    title: "Practice the interview. Keep the advantage.",
    description: "PrepMate is a private AI interview practice studio built for macOS.",
    siteName: "PrepMate",
    images: [{ url: publicAssetUrl("/og.png"), width: 1200, height: 630, alt: "PrepMate for macOS" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Practice the interview. Keep the advantage.",
    description: "PrepMate is a private AI interview practice studio built for macOS.",
    images: [publicAssetUrl("/og.png")],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
