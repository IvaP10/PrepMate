import { PrepMateLogo } from "./prepmate-logo";
import { MacDownloadButton } from "./mac-download-button";
import { SiteLink } from "./site-link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <SiteLink className="brand" href="/" aria-label="PrepMate home">
        <PrepMateLogo className="brand-logo" size={31} decorative />
        <span>PrepMate</span>
      </SiteLink>
      <nav className="site-nav" aria-label="Primary navigation">
        <SiteLink href="/#product">Product</SiteLink>
        <SiteLink href="/#how-it-works">How it works</SiteLink>
        <SiteLink href="/#privacy">Privacy</SiteLink>
        <SiteLink href="/support">Support</SiteLink>
      </nav>
      <MacDownloadButton className="header-cta">
        Download <span aria-hidden="true">↓</span>
      </MacDownloadButton>
    </header>
  );
}
