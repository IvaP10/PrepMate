import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"

export interface LegalSection {
  id: string
  title: string
}

interface LegalPageShellProps {
  eyebrow?: string
  title: string
  description: string
  updated?: string
  sections?: LegalSection[]
  children: React.ReactNode
}

export function LegalPageShell({
  eyebrow = "InterAI",
  title,
  description,
  updated,
  sections = [],
  children,
}: LegalPageShellProps) {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-background/95 px-6 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-1.5 transition-opacity hover:opacity-80">
            <ThemeLogo size={36} />
            <span className="text-base font-semibold text-foreground">InterAI</span>
          </Link>
          <Link
            href="/"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Home
          </Link>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-12 lg:grid-cols-[220px_minmax(0,1fr)] lg:py-16">
        <aside className="hidden lg:block">
          {sections.length > 0 && (
            <nav className="sticky top-8 flex flex-col gap-2 text-sm" aria-label={`${title} sections`}>
              <span className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Contents
              </span>
              {sections.map((section) => (
                <a
                  key={section.id}
                  href={`#${section.id}`}
                  className="rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  {section.title}
                </a>
              ))}
            </nav>
          )}
        </aside>

        <article className="max-w-3xl">
          <div className="mb-10 border-b border-border pb-8">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">{eyebrow}</p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
              {title}
            </h1>
            <p className="mt-5 text-base leading-7 text-muted-foreground">{description}</p>
            {updated && (
              <p className="mt-4 text-sm text-muted-foreground/80">Last updated: {updated}</p>
            )}
          </div>
          <div className="legal-prose space-y-9 text-foreground">{children}</div>
        </article>
      </div>
    </main>
  )
}
