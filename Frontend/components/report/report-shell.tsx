"use client"

import { useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import { ArrowLeft, Download, Loader2, Printer } from "lucide-react"

import { ThemeLogo } from "@/components/theme-logo"

interface ReportStat {
  label: string
  value: string
}

interface ReportShellProps {
  reportType: "technical" | "interview"
  title: string
  metadata: {
    date: string
    durationUsed?: string
    durationAllowed?: string
    profileType?: string | null
    isCustom?: boolean
    role?: string
    company?: string | null
    jobDescription?: string | null
    overallScore?: number | null
    stats?: ReportStat[]
  }
  sections: Array<{ id: string; title: string }>
  onDownloadJson?: () => void | Promise<void>
  downloadingJson?: boolean
  children: ReactNode
}

const profileLabels: Record<string, string> = {
  top_tier: "Top Tier",
  mid_tier: "Mid Tier",
  startup: "Startup",
}

export function ReportShell({ reportType, title, metadata, sections, onDownloadJson, downloadingJson, children }: ReportShellProps) {
  const [activeSection, setActiveSection] = useState(sections[0]?.id || "")
  const backHref = reportType === "technical" ? "/?tab=technical" : "/?tab=interview"
  const backLabel = reportType === "technical" ? "Technical" : "Interview"

  useEffect(() => {
    const nodes = sections
      .map((section) => document.getElementById(section.id))
      .filter((node): node is HTMLElement => Boolean(node))
    if (!nodes.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible?.target.id) setActiveSection(visible.target.id)
      },
      { rootMargin: "-20% 0px -65% 0px", threshold: [0.1, 0.4, 0.8] },
    )
    nodes.forEach((node) => observer.observe(node))
    return () => observer.disconnect()
  }, [sections])

  const scoreLabel = metadata.overallScore == null
    ? "Unable to Evaluate"
    : `${Math.round(metadata.overallScore)}/100`
  const normalizedProfileType = metadata.profileType?.trim().toLowerCase()
  const isCustom = metadata.isCustom ?? normalizedProfileType === "custom"
  const profileLabel = !isCustom && normalizedProfileType ? profileLabels[normalizedProfileType] : undefined
  const customTargetDetails = isCustom && Boolean(metadata.role || metadata.company || metadata.jobDescription)

  return (
    <main className="min-h-screen bg-background text-foreground" data-report-type={reportType}>
      <header className="border-b border-border bg-background/95" data-report-header>
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-4">
          <Link href="/" className="flex items-center gap-2" aria-label="PrepMate home">
            <ThemeLogo size={34} />
          <span className="text-base font-semibold">PrepMate</span>
          </Link>
          <div className="flex items-center gap-2">
            <button
              onClick={() => window.print()}
              data-report-export
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-secondary"
            >
              <Printer className="h-4 w-4" />
              Print / Save PDF
            </button>
            <button
              onClick={() => void onDownloadJson?.()}
              disabled={!onDownloadJson || downloadingJson}
              data-report-json-export
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60"
            >
              {downloadingJson ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {downloadingJson ? "Preparing JSON" : "Download JSON"}
            </button>
            <Link
              href={backHref}
              data-report-back
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-secondary"
            >
              <ArrowLeft className="h-4 w-4" />
              {backLabel}
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-8 px-6 py-10 lg:grid-cols-[220px_minmax(0,1fr)] lg:py-14">
        <aside className="hidden lg:block" data-report-sidebar>
          <nav className="sticky top-8 flex flex-col gap-1 text-sm" aria-label="Report sections">
            <span className="mb-2 px-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Contents
            </span>
            {sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                data-active={activeSection === section.id}
                className="rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground data-[active=true]:bg-secondary data-[active=true]:font-medium data-[active=true]:text-foreground"
              >
                {section.title}
              </a>
            ))}
          </nav>
        </aside>

        <article className="min-w-0 max-w-5xl space-y-8">
          <section className="border-b border-border pb-8" data-report-section>
            {profileLabel && (
              <div className="flex justify-end">
                <p className="text-base font-bold text-primary">
                  {profileLabel}
                </p>
              </div>
            )}
            <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border border-border bg-card px-4 py-3">
                <p className="text-xs font-bold text-muted-foreground">Date</p>
                <p className="mt-1 text-sm font-medium">{metadata.date}</p>
              </div>
              <div className="rounded-md border border-border bg-card px-4 py-3">
                <p className="text-xs font-bold text-muted-foreground">Time used / allowed</p>
                <p className="mt-1 text-sm font-medium">
                  {metadata.durationUsed || "—"} {metadata.durationAllowed ? `/ ${metadata.durationAllowed}` : ""}
                </p>
              </div>
              <div className="rounded-md border border-primary/30 bg-primary/5 px-4 py-3">
                <p className="text-xs font-bold text-muted-foreground">Overall score</p>
                <p className="mt-1 text-xl font-medium tabular-nums">{scoreLabel}</p>
              </div>
            </div>

            {customTargetDetails && (
              <details className="mt-4 rounded-md border border-border bg-card px-4 py-3">
                <summary className="cursor-pointer text-sm font-bold">View job description</summary>
                <div className="mt-3 border-t border-border pt-3 text-sm leading-6 text-muted-foreground">
                  {(metadata.role || metadata.company) && (
                    <p className="font-medium text-foreground">
                      {metadata.role || "Role not specified"}{metadata.company ? ` · ${metadata.company}` : ""}
                    </p>
                  )}
                  {metadata.jobDescription && (
                    <p className="mt-3 whitespace-pre-wrap">{metadata.jobDescription}</p>
                  )}
                </div>
              </details>
            )}
          </section>

          {!!metadata.stats?.length && (
            <section id="overall-result" data-report-section className="rounded-lg border border-border bg-card p-5">
              <h2 className="text-base font-bold">Overall result</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {metadata.stats.map((stat) => (
                  <div key={stat.label} className="rounded-md border border-border/70 bg-background px-4 py-3">
                    <p className="text-xs font-bold text-muted-foreground">{stat.label}</p>
                    <p className="mt-1 text-lg font-medium tabular-nums">{stat.value}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="space-y-10" data-report-content>{children}</div>
        </article>
      </div>
    </main>
  )
}
