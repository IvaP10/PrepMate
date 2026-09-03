import type { AnchorHTMLAttributes } from "react";
import { siteConfig } from "@/lib/site-config";

export function SiteLink({
  href,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const resolvedHref =
    typeof href === "string" && href.startsWith("/") && !href.startsWith("//")
      ? siteConfig.publicPath(href)
      : href;

  return <a {...props} href={resolvedHref} />;
}
