"use client"
import { ThemeLogo } from "@/components/theme-logo"
const footerLinks = [
  {
    heading: "Product",
    links: ["Features", "Pricing", "Mock Interview", "Practice Mode"],
  },
  {
    heading: "Company",
    links: ["About", "Blog", "Careers", "Contact"],
  },
  {
    heading: "Legal",
    links: ["Privacy Policy", "Terms of Service", "Cookie Policy"],
  },
]
interface FooterProps {
  theme?: "light" | "dark"
}
export function Footer({ theme = "dark" }: FooterProps) {
  return (
    <footer className="border-t border-border bg-background px-6 py-16">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-12 md:flex-row md:justify-between">
          <div className="flex max-w-xs flex-col gap-4">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); window.location.reload(); }}
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-shimmer text-base font-semibold">InterAI</span>
            </a>
            <p className="text-base leading-relaxed text-muted-foreground">
              AI-driven interview simulation that adapts to your professional background. Refine your communication skills with actionable, targeted feedback.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {footerLinks.map((group) => (
              <div key={group.heading} className="flex flex-col gap-3">
                <span className="text-sm font-semibold uppercase tracking-[0.15em] text-foreground">
                  {group.heading}
                </span>
                {group.links.map((link) => (
                  <a
                    key={link}
                    href="#"
                    className="text-base text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {link}
                  </a>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-8 md:flex-row">
          <p className="text-sm text-muted-foreground">
            © 2026 InterAI. All rights reserved.
          </p>
          <div className="flex gap-6">
            {["Twitter", "LinkedIn", "GitHub"].map((social) => (
              <a
                key={social}
                href="#"
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {social}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
