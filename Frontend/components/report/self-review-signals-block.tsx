"use client"

import { Info } from "lucide-react"
import type { SelfReviewSignalsSection, SelfReviewSignalDetail } from "@/types/premium-report"

interface SelfReviewSignalsBlockProps {
  signals?: SelfReviewSignalsSection
}

export function SelfReviewSignalsBlock({ signals }: SelfReviewSignalsBlockProps) {
  if (!signals) return null

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">{signals.title}</h2>
        <p className="text-sm leading-relaxed text-muted-foreground">{signals.verdict}</p>
      </div>
      <div className="space-y-3">
        {signals.details.map((detail, index) => {
          const signal = detail as SelfReviewSignalDetail
          return (
            <div key={index} className="report-self-review-event">
              <div className="flex items-center gap-2">
                <Info className="h-4 w-4 shrink-0 text-sky-500" />
                <span className="text-sm font-semibold text-foreground">{signal.event_type || "Signal"}</span>
                {signal.count !== undefined && signal.count > 0 && (
                  <span className="text-xs font-mono font-semibold text-muted-foreground">×{signal.count}</span>
                )}
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{signal.explanation}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
