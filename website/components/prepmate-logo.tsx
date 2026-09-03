import type { CSSProperties } from "react";
import { siteConfig } from "@/lib/site-config";

type PrepMateLogoProps = {
  className?: string;
  decorative?: boolean;
  size?: number;
};

export function PrepMateLogo({
  className = "",
  decorative = false,
  size = 32,
}: PrepMateLogoProps) {
  return (
    <span
      className={`prepmate-logo ${className}`.trim()}
      style={{ "--prepmate-logo-size": `${size}px` } as CSSProperties}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : "PrepMate logo"}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={siteConfig.publicPath("/images/light.svg")}
        alt=""
        width={size}
        height={size}
        decoding="async"
      />
    </span>
  );
}
