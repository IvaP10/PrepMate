"use client"
import { useState, useEffect } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Menu, X, Sun, Moon } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"
interface NavbarProps {
  onLogin: () => void
  onSignUp: () => void
  theme: "light" | "dark"
  onToggleTheme: () => void
  announcementVisible?: boolean
}
export function Navbar({ onLogin, onSignUp, theme, onToggleTheme, announcementVisible = false }: NavbarProps) {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 60)
    window.addEventListener("scroll", handler)
    return () => window.removeEventListener("scroll", handler)
  }, [])
  const handleScroll = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    e.preventDefault()
    const id = href.replace("#", "")
    const element = document.getElementById(id)
    if (element) {
      const fixedHeader = document.querySelector("[data-landing-header]")
      const headerHeight = fixedHeader?.getBoundingClientRect().height ?? (announcementVisible ? 104 : 64)
      const top = element.getBoundingClientRect().top + window.scrollY - headerHeight - 12

      window.scrollTo({
        behavior: "smooth",
        left: 0,
        top: Math.max(0, top),
      })
      window.history.replaceState(null, "", href)
    }
  }
  const navLinks = [
    { label: "How It Works", href: "#how-it-works" },
    { label: "Practice Modes", href: "#modes" },
    { label: "Performance", href: "#performance" },
    { label: "Pricing", href: "#pricing" },
  ]
  return (
    <nav
      className={`w-full transition-all duration-300 border-b ${
        scrolled
          ? "border-border bg-background/80 backdrop-blur-[20px]"
          : "border-border/40 bg-background/60 backdrop-blur-[12px] dark:bg-background/70"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link
          href="/"
          className="flex items-center gap-1.5 premium-transition hover:opacity-85"
        >
          <ThemeLogo size={36} />
          <span className="text-foreground text-base font-semibold">InterAI</span>
        </Link>
        <div className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              onClick={(e) => handleScroll(e, link.href)}
              className="text-sm text-muted-foreground premium-transition hover:text-foreground hover:-translate-y-[1px]"
            >
              {link.label}
            </a>
          ))}
        </div>
        <div className="hidden items-center gap-3 md:flex">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            className="h-8 w-8 text-muted-foreground hover:text-foreground premium-transition"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogin}
            className="text-sm text-muted-foreground hover:text-foreground hover:bg-transparent premium-transition hover:scale-[1.01]"
          >
            Log In
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onSignUp}
            className="rounded-md border-border bg-transparent text-sm text-foreground hover:bg-secondary premium-transition hover:scale-[1.015] active:scale-[0.985]"
          >
            Sign Up
          </Button>
        </div>
        <div className="flex items-center gap-2 md:hidden">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            className="h-8 w-8 text-muted-foreground"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-foreground"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>
      {mobileOpen && (
        <div className="border-b border-border bg-background/95 backdrop-blur-xl md:hidden">
          <div className="flex flex-col gap-1 px-6 py-4">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="rounded-lg px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                onClick={(e) => {
                  setMobileOpen(false)
                  handleScroll(e, link.href)
                }}
              >
                {link.label}
              </a>
            ))}
            <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
              <Button
                variant="ghost"
                onClick={() => { onLogin(); setMobileOpen(false) }}
                className="justify-start text-muted-foreground"
              >
                Log In
              </Button>
              <Button
                variant="outline"
                onClick={() => { onSignUp(); setMobileOpen(false) }}
                className="border-border text-foreground"
              >
                Sign Up
              </Button>
            </div>
          </div>
        </div>
      )}
    </nav>
  )
}
