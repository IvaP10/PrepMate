"use client"

import React from "react"
import { AlertTriangle, Zap, Target, Scale } from "lucide-react"
import type { AnalysisSection, AnalysisDetail, Severity } from "@/types/premium-report"

interface CodeForensicsBlockProps {
  logicTeardown?: AnalysisSection
  complexityOverheads?: AnalysisSection
  optimalDelta?: AnalysisSection
  edgeCaseForensics?: AnalysisSection
}

function SeverityStrip({ severity, label }: { severity: Severity; label: string }) {
  if (severity === "info") return null

  return (
    <span className="report-severity-strip" data-severity={severity}>
      {severity === "critical" && <AlertTriangle className="h-3.5 w-3.5" />}
      {severity === "warning" && <Zap className="h-3.5 w-3.5" />}
      {label}
    </span>
  )
}

function SectionBlock({ section, icon }: { section: AnalysisSection; icon: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
          {icon}
          {section.title}
        </h3>
        <SeverityStrip severity={section.severity} label={section.severity} />
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed italic">
        {section.verdict}
      </p>

      <div className="space-y-3">
        {section.details.map((detail, idx) => (
          <DetailCard key={idx} detail={detail} />
        ))}
      </div>
    </div>
  )
}

function DetailCard({ detail }: { detail: AnalysisDetail }) {
  return (
    <div className="report-pattern-callout p-4 space-y-2.5">
      {detail.line && (
        <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
          Line {detail.line}
        </span>
      )}

      <p className="text-sm leading-relaxed text-foreground/85">
        {detail.explanation}
      </p>

      {detail.snippet && (
        <pre className="report-code-failure">
          <code>{detail.snippet}</code>
        </pre>
      )}

      {detail.real_world_consequence && (
        <p className="text-xs leading-relaxed text-muted-foreground border-t border-border/40 pt-2 mt-2">
          <strong className="text-foreground/70">Real-world impact:</strong>{" "}
          {detail.real_world_consequence}
        </p>
      )}

      {detail.your_approach && detail.gold_standard && (
        <table className="report-delta-table mt-3">
          <thead>
            <tr>
              <th>Your Approach</th>
              <th>Gold Standard</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="font-mono text-sm">{detail.your_approach}</td>
              <td className="font-mono text-sm font-semibold">{detail.gold_standard}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  )
}

export function CodeForensicsBlock({
  logicTeardown,
  complexityOverheads,
  optimalDelta,
  edgeCaseForensics,
}: CodeForensicsBlockProps) {
  const sections = [
    { data: logicTeardown, icon: <Target className="h-4 w-4 text-muted-foreground" /> },
    { data: complexityOverheads, icon: <Zap className="h-4 w-4 text-muted-foreground" /> },
    { data: optimalDelta, icon: <Scale className="h-4 w-4 text-muted-foreground" /> },
    { data: edgeCaseForensics, icon: <AlertTriangle className="h-4 w-4 text-muted-foreground" /> },
  ].filter((s) => s.data)

  if (sections.length === 0) return null

  return (
    <div className="space-y-10">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          Technical Round: Deep Analysis
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Line-by-line forensic evaluation of your code, logic, complexity, and edge-case handling.
        </p>
      </div>

      <div className="space-y-8">
        {sections.map(({ data, icon }, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <div className="report-divider" />}
            <SectionBlock section={data!} icon={icon} />
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}
