"use client"

import React from "react"
import type {
  PremiumAnalysis,
  UnknownUnknown,
  VocalDeliverySection,
  ProctoringAuditSection,
} from "@/types/premium-report"
import { CodeForensicsBlock } from "@/components/report/code-forensics-block"
import { VocalDeliveryBlock } from "@/components/report/vocal-delivery-block"
import { ProctoringAuditBlock } from "@/components/report/proctoring-audit-block"

interface PremiumAnalysisSectionProps {
  premium: PremiumAnalysis
}

function UnknownUnknownsSection({ unknowns }: { unknowns: UnknownUnknown[] }) {
  if (unknowns.length === 0) return null

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          What You Didn&apos;t Know You Didn&apos;t Know
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Deep logical flaws, missed signals, and confidence gaps you did not realize you had.
        </p>
      </div>

      <div className="space-y-3">
        {unknowns.map((unknown, idx) => (
          <div key={idx} className="report-unknown-callout">
            <div className="flex items-start gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary font-mono mt-0.5">
                {idx + 1}
              </span>
              <div className="space-y-1.5">
                <h4 className="text-sm font-semibold text-foreground leading-snug">
                  {unknown.title}
                </h4>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {unknown.insight}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function PremiumAnalysisSection({ premium }: PremiumAnalysisSectionProps) {
  const isTechnical = premium.track === "technical"

  return (
    <div className="space-y-12">
      {/* Premium Analysis Header */}
      <div className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          Premium Analysis
        </h2>

        {/* Executive Summary Blockquote */}
        <div className="report-premium-blockquote">
          <p className="whitespace-pre-wrap">{premium.executive_summary}</p>
        </div>
      </div>

      {/* Track-Specific Deep Analysis */}
      {isTechnical ? (
        <CodeForensicsBlock
          logicTeardown={premium.logic_teardown}
          complexityOverheads={premium.complexity_overheads}
          optimalDelta={premium.optimal_delta}
          edgeCaseForensics={premium.edge_case_forensics}
        />
      ) : (
        <>
          <VocalDeliveryBlock
            contentAccuracy={premium.content_accuracy}
            vocalDelivery={premium.vocal_delivery as VocalDeliverySection | undefined}
          />
          <ProctoringAuditBlock
            audit={premium.proctoring_audit as ProctoringAuditSection | undefined}
          />
        </>
      )}

      {/* Unknown Unknowns */}
      <UnknownUnknownsSection unknowns={premium.unknown_unknowns} />
    </div>
  )
}
