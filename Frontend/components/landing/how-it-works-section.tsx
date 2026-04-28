"use client"
import { Upload, MonitorPlay, BarChart3 } from "lucide-react"
import { useState, useCallback, useRef } from "react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"
const steps = [
  {
    number: "01",
    icon: Upload,
    title: "Upload Your Professional Resume",
    description:
      "Securely upload your resume. Our system extracts your skills, experience, and education to tailor the interview simulation to your profile.",
  },
  {
    number: "02",
    icon: MonitorPlay,
    title: "Select Your Preferred Simulation Mode",
    description:
      "Choose a Mock Interview for a comprehensive, timed evaluation, or Practice Mode for an iterative learning experience with immediate feedback.",
  },
  {
    number: "03",
    icon: BarChart3,
    title: "Review Actionable Performance Insights",
    description:
      "Receive a detailed analytical breakdown of your performance, including areas of strength and targeted recommendations for continuous improvement.",
  },
]
function StepCard({
  step,
  index,
  isVisible,
  hoveredIndex,
  onHover,
}: {
  step: (typeof steps)[0]
  index: number
  isVisible: boolean
  hoveredIndex: number | null
  onHover: (index: number | null) => void
}) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [isHovering, setIsHovering] = useState(false)
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return
    const rect = cardRef.current.getBoundingClientRect()
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    })
  }, [])
  const handleMouseEnter = useCallback(() => {
    setIsHovering(true)
    onHover(index)
  }, [index, onHover])
  const handleMouseLeave = useCallback(() => {
    setIsHovering(false)
    onHover(null)
  }, [onHover])
  const isDimmed = hoveredIndex !== null && hoveredIndex !== index
  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="group relative flex flex-col overflow-hidden rounded-2xl bg-secondary/50 p-8"
      style={{
        opacity: isVisible ? (isDimmed ? 0.5 : 1) : 0,
        transform: isVisible ? "translateY(0)" : "translateY(15px)",
        filter: isDimmed ? "saturate(0.7)" : "saturate(1)",
        transition: `opacity 1.2s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.15}s, transform 1.2s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.15}s, filter 0.3s ease-out`,
      }}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300"
        style={{
          opacity: isHovering ? 1 : 0,
          background: `radial-gradient(400px circle at ${mousePos.x}px ${mousePos.y}px, rgba(255,255,255,0.04), transparent 40%)`,
        }}
      />
      <div className="relative z-10 mb-6 flex items-center justify-between">
        <span
          className="font-mono text-sm font-medium uppercase tracking-widest text-muted-foreground"
          style={{
            color: isHovering ? "var(--foreground)" : undefined,
            transition: "color 0.3s ease-out",
          }}
        >
          Step {step.number}
        </span>
        <step.icon className="h-5 w-5 text-accent-indigo/70" strokeWidth={1.5} />
      </div>
      <h3 className="relative z-10 mb-3 text-lg font-semibold text-foreground">
        {step.title}
      </h3>
      <p
        className="relative z-10 text-base leading-relaxed text-muted-foreground"
        style={{
          color: isHovering ? "var(--secondary-foreground)" : undefined,
          transition: "color 0.3s ease-out",
        }}
      >
        {step.description}
      </p>
      {index < steps.length - 1 && (
        <div className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-muted-foreground/30 md:block">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path
              d="M4.5 3l3 3-3 3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      )}
    </div>
  )
}
export function HowItWorksSection() {
  const { ref: sectionRef, isVisible } = useScrollReveal({ threshold: 0.15 })
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  return (
    <section ref={sectionRef} id="how-it-works" className="relative px-6 py-28">
      <div className="absolute inset-x-0 top-0 mx-auto h-px max-w-5xl bg-border" />
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto mb-20 max-w-2xl text-center">
          <span
            className={`mb-4 inline-block text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground ${isVisible ? 'animate-fade-in-up' : 'opacity-0'}`}
          >
            How It Works
          </span>
          <h2 className="overflow-hidden text-balance font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl md:text-5xl">
            <span className="block overflow-hidden pb-1">
              <span
                className={`text-shimmer inline-block ${isVisible ? 'animate-blur-in delay-100' : 'opacity-0'}`}
              >
                A streamlined process.
              </span>
            </span>
            <span className="block overflow-hidden pb-1">
              <span
                className={`text-shimmer-accent inline-block ${isVisible ? 'animate-blur-in delay-200' : 'opacity-0'}`}
              >
                Designed for absolute professional growth.
              </span>
            </span>
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {steps.map((step, i) => (
            <StepCard
              key={step.number}
              step={step}
              index={i}
              isVisible={isVisible}
              hoveredIndex={hoveredIndex}
              onHover={setHoveredIndex}
            />
          ))}
        </div>
      </div>
    </section>
  )
}
