"use client"

import React from "react"
import { Mic, MessageSquareQuote, AlertTriangle, Zap } from "lucide-react"
import type { AnalysisSection, VocalDeliverySection, Severity } from "@/types/premium-report"

interface VocalDeliveryBlockProps {
  contentAccuracy?: AnalysisSection
  vocalDelivery?: VocalDeliverySection
}

function SeverityStrip({ severity }: { severity: Severity }) {
  return (
    <span className="report-severity-strip" data-severity={severity}>
      {severity === "critical" && <AlertTriangle className="h-3.5 w-3.5" />}
      {severity === "warning" && <Zap className="h-3.5 w-3.5" />}
      {severity}
    </span>
  )
}

export function VocalDeliveryBlock({
  contentAccuracy,
  vocalDelivery,
}: VocalDeliveryBlockProps) {
  const hasContent = contentAccuracy || vocalDelivery

  if (!hasContent) return null

  return (
    <div className="space-y-10">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          Mock Interview: Deep Critique
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Scrutinizing your verbal answers against rigorous industry standards
          and analyzing delivery mechanics.
        </p>
      </div>

      <div className="space-y-8">
        {/* Content Accuracy Section */}
        {contentAccuracy && (
          <div className="space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                <MessageSquareQuote className="h-4 w-4 text-muted-foreground" />
                {contentAccuracy.title}
              </h3>
              <SeverityStrip severity={contentAccuracy.severity} />
            </div>

            <p className="text-sm text-muted-foreground leading-relaxed italic">
              {contentAccuracy.verdict}
            </p>

            <div className="space-y-3">
              {contentAccuracy.details.map((detail, idx) => (
                <div key={idx} className="report-pattern-callout p-4 space-y-2.5">
                  {detail.quote && (
                    <blockquote className="text-sm text-foreground/70 border-l-2 border-primary/30 pl-3 italic leading-relaxed">
                      {detail.quote}
                    </blockquote>
                  )}

                  <p className="text-sm leading-relaxed text-foreground/85">
                    {detail.explanation}
                  </p>

                  {detail.contrast && (
                    <div className="report-rewrite-block p-3 mt-2">
                      <p className="text-xs font-semibold text-primary uppercase tracking-wider mb-1">
                        What a top-tier engineer would say
                      </p>
                      <p className="text-sm leading-relaxed text-foreground/80">
                        {detail.contrast}
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {contentAccuracy && vocalDelivery && <div className="report-divider" />}

        {/* Vocal Delivery Section */}
        {vocalDelivery && (
          <div className="space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                <Mic className="h-4 w-4 text-muted-foreground" />
                {vocalDelivery.title}
              </h3>
              <SeverityStrip severity={vocalDelivery.severity} />
            </div>

            <p className="text-sm text-muted-foreground leading-relaxed italic">
              {vocalDelivery.verdict}
            </p>

            {/* Vocal Metrics Dashboard */}
            {vocalDelivery.metrics && (
              <div className="report-vocal-grid">
                <div className="report-vocal-metric">
                  <span className="metric-value">
                    {vocalDelivery.metrics.words_per_minute || "-"}
                  </span>
                  <span className="metric-label">Words / Min</span>
                </div>
                <div className="report-vocal-metric">
                  <span className="metric-value">
                    {vocalDelivery.metrics.filler_words_per_minute?.toFixed(1) || "-"}
                  </span>
                  <span className="metric-label">Fillers / Min</span>
                </div>
                <div className="report-vocal-metric">
                  <span className="metric-value">
                    {vocalDelivery.metrics.response_latency_avg != null
                      ? `${vocalDelivery.metrics.response_latency_avg}s`
                      : "-"}
                  </span>
                  <span className="metric-label">Avg Latency</span>
                </div>
                <div className="report-vocal-metric">
                  <span className="metric-value">
                    {vocalDelivery.metrics.clarity_proxy != null
                      ? `${vocalDelivery.metrics.clarity_proxy}%`
                      : "-"}
                  </span>
                  <span className="metric-label">Clarity</span>
                </div>
              </div>
            )}

            <div className="space-y-3">
              {vocalDelivery.details.map((detail, idx) => (
                <div key={idx} className="report-pattern-callout p-4">
                  <p className="text-sm leading-relaxed text-foreground/85">
                    {detail.explanation}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
