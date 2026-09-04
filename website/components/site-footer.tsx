import { MacDownloadButton } from "./mac-download-button";
import { PrepMateLogo } from "./prepmate-logo";
import { SiteLink } from "./site-link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-identity">
        <span className="footer-brand"><PrepMateLogo className="footer-logo" size={26} decorative /> PrepMate</span>
        <span>AI interview practice for macOS.</span>
      </div>
      <nav className="footer-links" aria-label="Footer navigation">
        <MacDownloadButton className="footer-download">Download</MacDownloadButton>
        <SiteLink href="/changelog">Release notes</SiteLink>
        <SiteLink href="/privacy">Privacy</SiteLink>
        <SiteLink href="/security">Security</SiteLink>
        <SiteLink href="/support">Support</SiteLink>
        <SiteLink href="/license">License</SiteLink>
      </nav>
      <span className="footer-platform">macOS only</span>
    </footer>
  );
}
