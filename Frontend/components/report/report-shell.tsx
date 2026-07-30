"use client"

import React, { useEffect, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Printer } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"

export interface ReportSectionMeta {
  id: string
  title: string
}

interface ReportShellProps {
  reportType: "technical" | "interview"
  title: string
  metadata: {
    date: string
    duration?: string
    role?: string
    itemCountLabel: string // e.g. "3 Problems Attempted" or "5 Questions Asked"
    overallScore?: number | null
  }
  sections: ReportSectionMeta[]
  children: React.ReactNode
}

export function ReportShell({
  reportType,
  title,
  metadata,
  sections,
  children,
}: ReportShellProps) {
  const [activeSection, setActiveSection] = useState<string>("")
  const backHref = reportType === "technical" ? "/?tab=technical" : "/?tab=interview"
  const backLabel = reportType === "technical" ? "Back to Coding" : "Back to Interview"

  useEffect(() => {
    if (sections.length === 0) return

    const observerOptions = {
      root: null,
      rootMargin: "-20% 0px -60% 0px",
      threshold: 0,
    }

    const handleIntersection = (entries: IntersectionObserverEntry[]) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          setActiveSection(entry.target.id)
        }
      })
    }

    const observer = new IntersectionObserver(handleIntersection, observerOptions)

    sections.forEach((sec) => {
      const el = document.getElementById(sec.id)
      if (el) observer.observe(el)
    })

    return () => {
      sections.forEach((sec) => {
        const el = document.getElementById(sec.id)
        if (el) observer.unobserve(el)
      })
    }
  }, [sections])

  const handlePrint = () => {
    window.print()
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* Sticky Top Header */}
      <header data-report-header className="sticky top-0 z-50 border-b border-border/70 bg-background/95 px-6 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-1.5 transition-opacity hover:opacity-80">
            <ThemeLogo size={36} />
            <span className="text-base font-semibold text-foreground">InterAI</span>
          </Link>
          
          <div className="flex items-center gap-3">
            <button
              onClick={handlePrint}
              data-report-export
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
            >
              <Printer className="h-4 w-4" />
              Print / Save PDF
            </button>
            <Link
              href={backHref}
              data-report-back
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
            >
              <ArrowLeft className="h-4 w-4" />
              {backLabel}
            </Link>
          </div>
        </div>
      </header>

      {/* Main Grid Layout */}
      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-12 lg:grid-cols-[220px_minmax(0,1fr)] lg:py-16" data-report-grid>
        {/* Sticky Sidebar ToC */}
        <aside className="hidden lg:block" data-report-sidebar>
          {sections.length > 0 && (
            <nav className="sticky top-24 flex flex-col gap-1 text-sm" aria-label="Report sections">
              <span className="mb-2 px-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Contents
              </span>
              {sections.map((sec) => (
                <a
                  key={sec.id}
                  href={`#${sec.id}`}
                  data-active={activeSection === sec.id}
                  className="report-toc-link"
                >
                  {sec.title}
                </a>
              ))}
            </nav>
          )}
        </aside>

        {/* Content Column */}
        <article className="max-w-3xl report-prose space-y-12">
          {/* Metadata Block */}
          <div className="pb-8 border-b border-border">
            <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl leading-none">
              {title}
            </h1>

            <div className="report-metadata mt-6 flex flex-wrap items-center gap-y-2 gap-x-4 text-sm text-muted-foreground">
              <span>{metadata.date}</span>
              {metadata.duration && (
                <>
                  <span className="sep" />
                  <span>{metadata.duration}</span>
                </>
              )}
              {metadata.role && (
                <>
                  <span className="sep" />
                  <span>{metadata.role}</span>
                </>
              )}
              <>
                <span className="sep" />
                <span>{metadata.itemCountLabel}</span>
              </>
            </div>

            {metadata.overallScore !== undefined && metadata.overallScore !== null && (
              <div className="mt-6 flex items-center gap-3">
                <div className="report-score-badge">
                  <span className="score">{Math.round(metadata.overallScore)}%</span>
                  <span className="label ml-2">Overall Score</span>
                </div>
              </div>
            )}
          </div>

          {/* Report Content */}
          <div className="space-y-12">
            {children}
          </div>
        </article>
      </div>
    </main>
  )
}
