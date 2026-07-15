"use client"
import { TrendingUp, Eye, Gauge, Lightbulb } from "lucide-react"
interface PerformanceMetricsProps {
  variant?: "compact" | "full"
  engagement?: { value: number; label: string }
  cameraContact?: { value: number; label: string }
  pace?: { wpm: number; label: string }
  dynamicTip?: string | null
}
function MetricGauge({
  icon: Icon,
  label,
  value,
  displayValue,
}: {
  icon: typeof TrendingUp
  label: string
  value: number
  displayValue: string
}) {
  const clampedValue = Math.max(0, Math.min(100, value))
  return (
    <div className="flex items-center gap-3">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-secondary">
        <Icon className="w-4 h-4 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-muted-foreground truncate">{label}</span>
          <span className="text-xs font-semibold text-foreground tabular-nums">
            {displayValue}
          </span>
        </div>
        <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-primary transition-all duration-700 ease-out"
            style={{ width: `${clampedValue}%` }}
          />
        </div>
      </div>
    </div>
  )
}
export function PerformanceMetrics({
  variant = "compact",
  engagement = { value: 50, label: "Moderate" },
  cameraContact = { value: 50, label: "Optimal" },
  pace = { wpm: 0, label: "-" },
  dynamicTip = null,
}: PerformanceMetricsProps) {
  const paceValue = pace.wpm > 0
    ? Math.max(0, Math.min(100, 100 - Math.abs(pace.wpm - 140) * 1.2))
    : 50
  return (
    <div className="bg-card rounded-xl border border-border p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Performance Vitals</h3>
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <span className="text-xs text-muted-foreground">Live</span>
        </div>
      </div>
      <div className="space-y-3">
        <MetricGauge
          icon={TrendingUp}
          label="Engagement"
          value={engagement.value}
          displayValue={`${engagement.label} · ${engagement.value}%`}
        />
        <MetricGauge
          icon={Eye}
          label="Camera Contact"
          value={cameraContact.value}
          displayValue={`${cameraContact.label} · ${cameraContact.value}%`}
        />
        <MetricGauge
          icon={Gauge}
          label="Pace"
          value={paceValue}
          displayValue={pace.wpm > 0 ? `${pace.label} · ${pace.wpm} wpm` : pace.label}
        />
      </div>
      {variant === "full" && dynamicTip && (
        <div className="mt-3 p-3 rounded-lg bg-secondary border border-border">
          <div className="flex items-start gap-2">
            <Lightbulb className="w-4 h-4 text-primary mt-0.5 shrink-0" />
            <p className="text-xs text-muted-foreground leading-relaxed">{dynamicTip}</p>
          </div>
        </div>
      )}
    </div>
  )
}
