"use client"
import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Menu, X, Sun, Moon } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"
interface NavbarProps {
  onLogin: () => void
  onSignUp: () => void
  theme: "light" | "dark"
  onToggleTheme: () => void
}
export function Navbar({ onLogin, onSignUp, theme, onToggleTheme }: NavbarProps) {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20)
    window.addEventListener("scroll", handler)
    return () => window.removeEventListener("scroll", handler)
  }, [])
  const navLinks = [
    { label: "Features", href: "#features" },
    { label: "How It Works", href: "#how-it-works" },
    { label: "Pricing", href: "#pricing" },
  ]
  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? "border-b border-border bg-background/60 backdrop-blur-xl dark:bg-[rgba(0,0,0,0.6)]"
          : "bg-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <a
          href="/"
          onClick={(e) => { e.preventDefault(); window.location.reload(); }}
          className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
        >
          <ThemeLogo size={36} />
          <span className="text-shimmer text-base font-semibold">InterAI</span>
        </a>
        <div className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="text-base text-muted-foreground transition-colors hover:text-foreground"
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
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogin}
            className="text-base text-muted-foreground hover:text-foreground hover:bg-transparent"
          >
            Log In
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onSignUp}
            className="rounded-full border-border bg-transparent text-base text-foreground hover:bg-secondary"
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
                onClick={() => setMobileOpen(false)}
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
