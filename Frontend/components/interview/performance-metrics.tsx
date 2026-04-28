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
  color,
}: {
  icon: typeof TrendingUp
  label: string
  value: number
  displayValue: string
  color: string
}) {
  const clampedValue = Math.max(0, Math.min(100, value))
  return (
    <div className="flex items-center gap-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center"
        style={{ backgroundColor: `${color}20` }}
      >
        <Icon className="w-4 h-4" style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-white/60 truncate">{label}</span>
          <span className="text-xs font-semibold text-white/90 tabular-nums">
            {displayValue}
          </span>
        </div>
        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700 ease-out"
            style={{
              width: `${clampedValue}%`,
              backgroundColor: color,
            }}
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
  pace = { wpm: 0, label: "—" },
  dynamicTip = null,
}: PerformanceMetricsProps) {
  const paceValue = pace.wpm > 0
    ? Math.max(0, Math.min(100, 100 - Math.abs(pace.wpm - 140) * 1.2))
    : 50
  return (
    <div className="bg-white/[0.03] backdrop-blur-md rounded-xl border border-white/10 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white/80">Performance Vitals</h3>
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] text-white/40">LIVE</span>
        </div>
      </div>
      <div className="space-y-3">
        <MetricGauge
          icon={TrendingUp}
          label="Engagement"
          value={engagement.value}
          displayValue={`${engagement.label} · ${engagement.value}%`}
          color="#10b981"
        />
        <MetricGauge
          icon={Eye}
          label="Camera Contact"
          value={cameraContact.value}
          displayValue={`${cameraContact.label} · ${cameraContact.value}%`}
          color="#6366f1"
        />
        <MetricGauge
          icon={Gauge}
          label="Pace"
          value={paceValue}
          displayValue={pace.wpm > 0 ? `${pace.label} · ${pace.wpm} wpm` : pace.label}
          color="#f59e0b"
        />
      </div>
      {variant === "full" && dynamicTip && (
        <div className="mt-3 p-3 rounded-lg bg-gradient-to-r from-indigo-500/10 to-purple-500/10 border border-indigo-500/20">
          <div className="flex items-start gap-2">
            <Lightbulb className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
            <p className="text-xs text-white/70 leading-relaxed">{dynamicTip}</p>
          </div>
        </div>
      )}
    </div>
  )
}
