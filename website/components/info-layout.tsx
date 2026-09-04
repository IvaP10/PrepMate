import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";
import { SiteLink } from "./site-link";

export function InfoLayout({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children: React.ReactNode;
}) {
  return (
    <main className="site-shell">
      <SiteHeader />
      <div className="inner-page">
        <SiteLink className="back-link" href="/">← PrepMate home</SiteLink>
        <h1 className="inner-title">{title}</h1>
        <p className="inner-lede">{lede}</p>
        <div className="inner-content">{children}</div>
      </div>
      <SiteFooter />
    </main>
  );
}
