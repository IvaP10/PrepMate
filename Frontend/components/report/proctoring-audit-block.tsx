"use client"

import React from "react"
import { ShieldCheck, ShieldAlert, ShieldX, AlertTriangle } from "lucide-react"
import type { ProctoringAuditSection, Severity } from "@/types/premium-report"

interface ProctoringAuditBlockProps {
  audit?: ProctoringAuditSection
}

function GradeIcon({ grade }: { grade: string }) {
  if (grade === "A" || grade === "B") {
    return <ShieldCheck className="h-5 w-5" />
  }
  if (grade === "C") {
    return <ShieldAlert className="h-5 w-5" />
  }
  return <ShieldX className="h-5 w-5" />
}

export function ProctoringAuditBlock({ audit }: ProctoringAuditBlockProps) {
  if (!audit) return null

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          {audit.title}
        </h2>

        <div className="flex flex-wrap items-center gap-3">
          <span
            className="report-integrity-badge"
            data-grade={audit.integrity_grade}
          >
            <GradeIcon grade={audit.integrity_grade} />
            Grade {audit.integrity_grade}
          </span>

          <span className="text-xs text-muted-foreground">
            Risk score: {audit.risk_score}/100 · Level: {audit.risk_level}
          </span>
        </div>

        <p className="text-sm text-muted-foreground leading-relaxed italic mt-1">
          {audit.verdict}
        </p>
      </div>

      {/* Event Timeline */}
      <div className="space-y-3">
        {audit.details.map((detail, idx) => {
          const eventDetail = detail as {
            event_type?: string
            count?: number
            event_severity?: string
            explanation: string
          }
          const severity = (eventDetail.event_severity || "info") as Severity

          return (
            <div
              key={idx}
              className="report-proctor-event"
              data-severity={severity}
            >
              <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2">
                  {severity === "critical" && (
                    <AlertTriangle className="h-4 w-4 text-rose-500 shrink-0" />
                  )}
                  {severity === "warning" && (
                    <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
                  )}
                  <span className="text-sm font-semibold text-foreground">
                    {eventDetail.event_type || "Event"}
                  </span>
                </div>

                {eventDetail.count !== undefined && eventDetail.count > 0 && (
                  <span className="text-xs font-mono font-semibold text-muted-foreground">
                    ×{eventDetail.count}
                  </span>
                )}
              </div>

              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                {eventDetail.explanation}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
