"use client"
import Link from "next/link"
import { ThemeLogo } from "@/components/theme-logo"
const footerLinks = [
  {
    heading: "Product",
    links: [
      { label: "About", href: "/about" },
      { label: "How It Works", href: "/#how-it-works" },
      { label: "What You Practice", href: "/#modes" },
      { label: "Feedback", href: "/#performance" },
      { label: "Pricing", href: "/#pricing" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy Policy", href: "/privacy" },
      { label: "Terms of Service", href: "/terms" },
      { label: "Cookie Policy", href: "/privacy#cookies" },
    ],
  },
]
interface FooterProps {
  theme?: "light" | "dark"
}
export function Footer({ theme = "dark" }: FooterProps) {
  return (
    <footer className="relative z-10 border-t border-border/80 bg-background/95 px-6 py-14 backdrop-blur-md">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-12 md:flex-row md:justify-between">
          <div className="flex max-w-xs flex-col gap-4">
            <Link
              href="/"
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-foreground text-base font-semibold">InterAI</span>
            </Link>
            <p className="text-base leading-relaxed text-foreground/75">Interview practice tailored to your role, with feedback that turns into your next step.</p>
          </div>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {footerLinks.map((group) => (
              <div key={group.heading} className="flex flex-col gap-3">
                <span className="text-sm font-semibold text-foreground">
                  {group.heading}
                </span>
                {group.links.map((link) => (
                  <Link
                    key={link.label}
                    href={link.href}
                    className="text-base text-foreground/70 transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-8 md:flex-row">
          <p className="text-sm text-foreground/65">
            © 2026 InterAI. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  )
}
