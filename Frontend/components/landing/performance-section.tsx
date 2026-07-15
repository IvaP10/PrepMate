"use client"
import { useState, useCallback, useRef, useEffect } from "react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"
import { Code, MessageSquare, TrendingUp, TrendingDown } from "lucide-react"
import { motion, useAnimation } from "framer-motion"

/* ── Data ─────────────────────────────────────────────────────────────── */

const barData = [
  { label: "Arrays",        value: 90 },
  { label: "Trees",         value: 75 },
  { label: "DP",            value: 65 },
  { label: "System Design", value: 95 },
  { label: "Graphs",        value: 70 },
]

const lineData = [
  { label: "Q1", value: 70 },
  { label: "Q2", value: 75 },
  { label: "Q3", value: 60 },
  { label: "Q4", value: 85 },
  { label: "Q5", value: 90 },
]

const yLabels = ["100%", "75%", "50%", "25%", "0%"]

/* ── SVG dimensions ───────────────────────────────────────────────────── */

const BAR_SVG_W   = 380
const BAR_SVG_H   = 180
const BAR_PAD_L   = 40   // left padding for y-axis labels
const BAR_PAD_B   = 24   // bottom padding for x-axis labels
const BAR_CHART_H = BAR_SVG_H - BAR_PAD_B
const BAR_W       = 32
const BAR_GAP     = (BAR_SVG_W - BAR_PAD_L - barData.length * BAR_W) / (barData.length + 1)

const LINE_SVG_W  = 380
const LINE_SVG_H  = 180
const LINE_PAD_X  = 30
const LINE_PAD_B  = 24
const LINE_CHART_H = LINE_SVG_H - LINE_PAD_B

/* ── Bar chart helpers ────────────────────────────────────────────────── */

function barX(i: number) {
  return BAR_PAD_L + BAR_GAP + i * (BAR_W + BAR_GAP)
}
function barH(value: number) {
  return (value / 100) * BAR_CHART_H
}

/* ── Line chart helpers ───────────────────────────────────────────────── */

const lineUsableW = LINE_SVG_W - LINE_PAD_X * 2
const lineStepX   = lineUsableW / (lineData.length - 1)

const linePoints = lineData.map((d, i) => ({
  x: LINE_PAD_X + i * lineStepX,
  y: LINE_CHART_H - (d.value / 100) * LINE_CHART_H,
}))

const linePath = linePoints
  .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
  .join(" ")

const fillPath = `${linePath} L ${linePoints[linePoints.length - 1].x} ${LINE_CHART_H} L ${linePoints[0].x} ${LINE_CHART_H} Z`

/* ── Compute total line length for strokeDasharray ────────────────────── */

function computeLineLength() {
  let total = 0
  for (let i = 1; i < linePoints.length; i++) {
    const dx = linePoints[i].x - linePoints[i - 1].x
    const dy = linePoints[i].y - linePoints[i - 1].y
    total += Math.sqrt(dx * dx + dy * dy)
  }
  return total
}

const LINE_TOTAL_LENGTH = computeLineLength()

/* ── Component ────────────────────────────────────────────────────────── */

export function PerformanceSection() {
  const { ref: sectionRef, isVisible } = useScrollReveal({ threshold: 0.12 })

  /*
   * Animation strategy:
   *  – barAnimKey / lineAnimKey increment on hover-enter,
   *    which remounts motion elements to replay the "from 0 → full" animation.
   *  – When NOT animating (the default resting state), we render plain SVG
   *    elements at their final values so the chart is always fully visible.
   */
  const [barAnimKey, setBarAnimKey]   = useState(0)
  const [barAnimating, setBarAnimating] = useState(false)
  const barTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [lineAnimKey, setLineAnimKey]   = useState(0)
  const [lineAnimating, setLineAnimating] = useState(false)
  const lineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleBarHoverEnter = useCallback(() => {
    if (barTimerRef.current) clearTimeout(barTimerRef.current)
    setBarAnimKey((k) => k + 1)
    setBarAnimating(true)
    // after the longest bar animation finishes, mark done
    barTimerRef.current = setTimeout(() => {
      setBarAnimating(false)
    }, 800 + barData.length * 80) // spring duration ≈ 600ms + stagger
  }, [])

  const handleLineHoverEnter = useCallback(() => {
    if (lineTimerRef.current) clearTimeout(lineTimerRef.current)
    setLineAnimKey((k) => k + 1)
    setLineAnimating(true)
    lineTimerRef.current = setTimeout(() => {
      setLineAnimating(false)
    }, 1600) // line draw 1.2s + dots stagger
  }, [])

  // cleanup timers
  useEffect(() => {
    return () => {
      if (barTimerRef.current) clearTimeout(barTimerRef.current)
      if (lineTimerRef.current) clearTimeout(lineTimerRef.current)
    }
  }, [])

  return (
    <section
      id="performance"
      className="relative px-6 pt-16 pb-32 md:pt-20 md:pb-44 border-t border-border/40"
    >
      <div ref={sectionRef} className="mx-auto max-w-5xl">
        {/* Section Header */}
        <div className="mx-auto mb-10 max-w-3xl text-center md:mb-12">
          <span
            className={`mb-4 inline-block text-xs font-semibold uppercase tracking-[0.25em] text-primary ${
              isVisible ? "animate-fade-in-up" : "opacity-0"
            }`}
          >
            Personalised Reports
          </span>
          <h2
            className={`text-balance text-4xl sm:text-5xl md:text-6xl font-semibold tracking-[-0.03em] leading-[1.05] text-foreground transition-all duration-700 ${
              isVisible ? "animate-blur-in delay-100" : "opacity-0"
            }`}
          >
            Your performance, dissected.
          </h2>
          <p
            className={`mt-6 text-base text-muted-foreground leading-[1.7] ${
              isVisible ? "animate-fade-in-up delay-300" : "opacity-0"
            }`}
          >
            After every session, get a breakdown that separates how you communicate from how you solve problems. Communication skills and technical skills, always scored independently.
          </p>
        </div>

        {/* Bento Grid */}
        <div
          className={`grid grid-cols-1 md:grid-cols-2 gap-6 ${
            isVisible ? "animate-fade-in-up delay-300" : "opacity-0"
          }`}
        >
          {/* ═══════════════════════════════════════════════════════════ */}
          {/* Card 1: Technical Performance - Bar Chart                   */}
          {/* ═══════════════════════════════════════════════════════════ */}
          <div
            onMouseEnter={handleBarHoverEnter}
            className="landing-solid-card rounded-xl border border-border/50 p-6 premium-transition hover:scale-[1.01] hover:shadow-xl hover:shadow-black/[0.06] dark:hover:shadow-black/[0.18]"
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2.5">
                <Code className="h-5 w-5 text-primary" strokeWidth={1.5} />
                <h3 className="text-base font-bold text-foreground">Technical Performance</h3>
              </div>
              <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">
                System Design + DSA
              </span>
            </div>

            {/* Bar Chart (inline SVG) */}
            <div className="rounded-lg bg-background border border-border/50 p-4">
              <svg
                viewBox={`0 0 ${BAR_SVG_W} ${BAR_SVG_H}`}
                className="w-full h-auto"
                preserveAspectRatio="xMidYMid meet"
              >
                {/* Y-axis labels */}
                {yLabels.map((label, i) => {
                  const y = (i / (yLabels.length - 1)) * BAR_CHART_H
                  return (
                    <text
                      key={label}
                      x={BAR_PAD_L - 8}
                      y={y + 3}
                      textAnchor="end"
                      className="fill-muted-foreground/60"
                      style={{ fontSize: "9px", fontFamily: "ui-monospace, monospace" }}
                    >
                      {label}
                    </text>
                  )
                })}

                {/* Grid lines */}
                {yLabels.map((label, i) => {
                  const y = (i / (yLabels.length - 1)) * BAR_CHART_H
                  return (
                    <line
                      key={`grid-${label}`}
                      x1={BAR_PAD_L}
                      y1={y}
                      x2={BAR_SVG_W}
                      y2={y}
                      stroke="var(--border)"
                      strokeOpacity={i === yLabels.length - 1 ? 0.5 : 0.3}
                      strokeWidth={1}
                    />
                  )
                })}

                {/* Bars — animate from 0 → full on hover; rest at full */}
                {barData.map((bar, i) => {
                  const x = barX(i)
                  const maxH = barH(bar.value)
                  return (
                    <g key={bar.label}>
                      {barAnimating ? (
                        <motion.rect
                          key={`bar-anim-${barAnimKey}-${i}`}
                          x={x}
                          width={BAR_W}
                          rx={4}
                          ry={4}
                          fill="var(--primary)"
                          fillOpacity={0.6 + (bar.value / 100) * 0.4}
                          initial={{ height: 0, y: BAR_CHART_H }}
                          animate={{
                            height: maxH,
                            y: BAR_CHART_H - maxH,
                          }}
                          transition={{
                            type: "spring",
                            stiffness: 120,
                            damping: 18,
                            delay: i * 0.08,
                          }}
                        />
                      ) : (
                        <rect
                          x={x}
                          y={BAR_CHART_H - maxH}
                          width={BAR_W}
                          height={maxH}
                          rx={4}
                          ry={4}
                          fill="var(--primary)"
                          fillOpacity={0.6 + (bar.value / 100) * 0.4}
                        />
                      )}
                      {/* X-axis label */}
                      <text
                        x={x + BAR_W / 2}
                        y={BAR_SVG_H - 4}
                        textAnchor="middle"
                        className="fill-muted-foreground"
                        style={{ fontSize: "9px", fontWeight: 500 }}
                      >
                        {bar.label}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-border/30">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground">Code Efficiency: 78%</span>
                <TrendingUp className="h-3.5 w-3.5 text-primary" />
              </div>
              <span className="text-sm font-mono text-muted-foreground">Avg Complexity: O(n log n)</span>
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════ */}
          {/* Card 2: Interview Performance - Line Chart                  */}
          {/* ═══════════════════════════════════════════════════════════ */}
          <div
            onMouseEnter={handleLineHoverEnter}
            className="landing-solid-card rounded-xl border border-border/50 p-6 transition-all duration-300 ease-out hover:-translate-y-1 hover:scale-[1.015] hover:shadow-xl hover:shadow-black/[0.06] dark:hover:shadow-black/[0.18]"
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2.5">
                <MessageSquare className="h-5 w-5 text-primary" strokeWidth={1.5} />
                <h3 className="text-base font-bold text-foreground">Interview Performance</h3>
              </div>
              <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">
                Pacing &amp; Clarity
              </span>
            </div>

            {/* Line Chart (inline SVG) */}
            <div className="rounded-lg bg-background border border-border/50 p-4">
              <svg
                viewBox={`0 0 ${LINE_SVG_W} ${LINE_SVG_H}`}
                className="w-full h-auto overflow-visible"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <linearGradient id="areaFillGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.12" />
                    <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
                  </linearGradient>
                </defs>

                {/* Grid lines */}
                {[0, 25, 50, 75].map((pct) => {
                  const y = LINE_CHART_H - (pct / 100) * LINE_CHART_H
                  return (
                    <line
                      key={pct}
                      x1={LINE_PAD_X}
                      y1={y}
                      x2={LINE_SVG_W - LINE_PAD_X}
                      y2={y}
                      stroke="var(--border)"
                      strokeOpacity={pct === 0 ? 0.5 : 0.3}
                      strokeWidth={1}
                    />
                  )
                })}

                {lineAnimating ? (
                  <>
                    {/* Area fill — fades in after line is drawn */}
                    <motion.path
                      key={`area-anim-${lineAnimKey}`}
                      d={fillPath}
                      fill="url(#areaFillGrad)"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.6, delay: 0.8 }}
                    />

                    {/* Animated line using strokeDasharray for reliable drawing */}
                    <motion.path
                      key={`line-anim-${lineAnimKey}`}
                      d={linePath}
                      fill="none"
                      stroke="var(--primary)"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      vectorEffect="non-scaling-stroke"
                      strokeDasharray={LINE_TOTAL_LENGTH}
                      initial={{ strokeDashoffset: LINE_TOTAL_LENGTH, opacity: 1 }}
                      animate={{ strokeDashoffset: 0 }}
                      transition={{
                        duration: 1.2,
                        ease: [0.25, 1, 0.5, 1],
                      }}
                    />

                    {/* Data point dots — staggered fade-in */}
                    {linePoints.map((p, i) => (
                      <motion.circle
                        key={`dot-anim-${lineAnimKey}-${i}`}
                        cx={p.x}
                        cy={p.y}
                        r={5}
                        fill="var(--primary)"
                        stroke="white"
                        strokeWidth={2}
                        initial={{ opacity: 0, scale: 0.3 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{
                          duration: 0.35,
                          delay: 0.2 + i * 0.2,
                          ease: [0.34, 1.56, 0.64, 1],
                        }}
                      />
                    ))}
                  </>
                ) : (
                  <>
                    {/* Static area fill */}
                    <path
                      d={fillPath}
                      fill="url(#areaFillGrad)"
                    />

                    {/* Static line */}
                    <path
                      d={linePath}
                      fill="none"
                      stroke="var(--primary)"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      vectorEffect="non-scaling-stroke"
                    />

                    {/* Static dots */}
                    {linePoints.map((p, i) => (
                      <circle
                        key={`dot-static-${i}`}
                        cx={p.x}
                        cy={p.y}
                        r={5}
                        fill="var(--primary)"
                        stroke="white"
                        strokeWidth={2}
                      />
                    ))}
                  </>
                )}

                {/* X-axis labels */}
                {lineData.map((d, i) => (
                  <text
                    key={d.label}
                    x={linePoints[i].x}
                    y={LINE_SVG_H - 4}
                    textAnchor="middle"
                    className="fill-muted-foreground/60"
                    style={{ fontSize: "9px", fontFamily: "ui-monospace, monospace" }}
                  >
                    {d.label}
                  </text>
                ))}
              </svg>
            </div>

            {/* Footer */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-4 pt-4 border-t border-border/30">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground">Clarity Score: 84%</span>
                <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary/10 text-primary">Good</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-muted-foreground">Filler Words: 2.1/min</span>
                <TrendingDown className="h-3.5 w-3.5 text-primary" />
              </div>
              <span className="text-sm text-muted-foreground">Avg Latency: 1.8s</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
