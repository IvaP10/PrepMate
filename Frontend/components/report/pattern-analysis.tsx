import { AlertTriangle } from "lucide-react"

interface Pattern {
  name: string
  countLabel?: string
  description: string
  isPositive?: boolean
}

interface PatternAnalysisProps {
  patterns: Pattern[]
}

export function PatternAnalysis({ patterns }: PatternAnalysisProps) {
  if (patterns.length === 0) return null

  return (
    <section id="patterns" data-report-section className="scroll-margin-top: 5rem space-y-6">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Pattern Analysis</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Repeated issues identified across your session evidence.
        </p>
        <div className="grid gap-4 mt-2">
          {patterns.map((pat, idx) => (
            <div key={idx} className="report-pattern-callout p-4 flex gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-semibold text-foreground text-sm">{pat.name}</span>
                  {pat.countLabel && (
                    <span className="text-[10px] uppercase font-semibold text-amber-600 dark:text-amber-400">
                      {pat.countLabel}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{pat.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
