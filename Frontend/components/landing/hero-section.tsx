"use client"
import { useState, useRef } from "react"

interface HeroSectionProps {
  onGetStarted: () => void
  theme: "light" | "dark"
}

function IntegratedRealityGraphic() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState({ x: 0, y: 0 })
  const [isHovered, setIsHovered] = useState(false)

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const x = (e.clientX - rect.left) / rect.width
    const y = (e.clientY - rect.top) / rect.height
    setCoords({ x: x - 0.5, y: y - 0.5 })
    setIsHovered(true)
  }

  const handleMouseLeave = () => {
    setCoords({ x: 0, y: 0 })
    setIsHovered(false)
  }

  const rotateX = -coords.y * 8
  const rotateY = coords.x * 8
  const shadowX = -coords.x * 20
  const shadowY = -coords.y * 20

  const containerStyle = {
    transform: `perspective(2000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`,
    transition: isHovered ? "none" : "transform 1.2s cubic-bezier(0.16, 1, 0.3, 1)",
    transformStyle: "preserve-3d" as const,
  }

  return (
    <div className="w-full flex items-center justify-center overflow-visible h-[280px] sm:h-[340px] md:h-[400px]">
      <div
        ref={containerRef}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        className="relative w-[540px] h-[400px] select-none scale-[0.65] sm:scale-[0.85] md:scale-100 origin-center shrink-0 overflow-visible"
        style={containerStyle}
      >
        {/* SVG Connecting Lines */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0 overflow-visible opacity-55"
          viewBox="0 0 540 400"
          fill="none"
        >
          <path d="M 160,90 C 200,90 200,165 225,165" stroke="var(--color-primary, #3B82F6)" strokeWidth="2.5" strokeDasharray="4 4" className="animate-pulse" />
          <path d="M 270,240 C 220,240 180,310 160,310" stroke="var(--color-primary, #3B82F6)" strokeWidth="2.5" strokeDasharray="4 4" className="animate-pulse" />
          <path d="M 330,240 C 370,240 405,290 425,290" stroke="var(--color-primary, #3B82F6)" strokeWidth="2.5" strokeDasharray="4 4" className="animate-pulse" />
        </svg>

        {/* 1. Input Card (Top-Left) */}
        <div
          className="landing-solid-card absolute top-[40px] left-[10px] w-[170px] shadow-lg border border-border/80 p-4 rounded-xl flex flex-col z-10 transition-all duration-300"
          style={{
            transform: `translateZ(${isHovered ? "45px" : "0px"})`,
            boxShadow: isHovered
              ? `${shadowX}px ${shadowY}px 40px -10px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(var(--foreground), 0.05)`
              : "0 10px 20px -10px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(var(--foreground), 0.03)",
          }}
        >
          <div className="text-[8px] font-bold uppercase tracking-[0.1em] text-muted-foreground mb-2">
            Role profile
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 text-[9.5px] font-bold w-fit mb-3.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            Top-Tier
          </div>
          <div className="flex items-center gap-2 text-[9.5px] font-semibold text-primary">
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="3">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            Resume Uploaded
          </div>
        </div>

        {/* 2. The Engine (Center) */}
        <div
          className="landing-solid-card absolute top-[100px] left-[200px] w-[310px] shadow-2xl border border-border bg-white rounded-xl overflow-hidden z-20 transition-all duration-300"
          style={{
            transform: `translateZ(${isHovered ? "20px" : "0px"})`,
            boxShadow: isHovered
              ? `${shadowX * 0.5}px ${shadowY * 0.5}px 50px -15px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(var(--foreground), 0.06)`
              : "0 15px 35px -15px rgba(0, 0, 0, 0.12), 0 0 0 1px rgba(var(--foreground), 0.03)",
          }}
        >
          <div className="flex items-center justify-between border-b border-border/80 px-4 py-2.5 bg-secondary/35 shrink-0">
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-[#ff5f57]" />
              <div className="h-1.5 w-1.5 rounded-full bg-[#ffbd2e]" />
              <div className="h-1.5 w-1.5 rounded-full bg-[#28c840]" />
              <span className="ml-2 text-[7.5px] font-mono text-muted-foreground uppercase tracking-widest leading-none">
                Live interview
              </span>
            </div>
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-ping" />
          </div>

          <div className="p-4 bg-background/50">
            <div className="flex items-start gap-2.5">
              <div className="w-6 h-6 rounded-md bg-secondary flex items-center justify-center shrink-0 border border-border">
                <svg className="w-3.5 h-3.5 text-foreground/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
              <div className="bg-secondary/40 rounded-lg p-3 border border-border/60">
                <span className="block text-[7px] font-bold text-muted-foreground uppercase tracking-wider mb-1">
                  AI Interviewer
                </span>
                <p className="text-[9px] leading-[1.5] text-foreground/80 font-medium">
                  &ldquo;I see you listed a database migration project on your resume. How did you design the schema migration path to support zero downtime while transitioning active traffic?&rdquo;
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* 3. Output Card A: Technical Performance (Bottom-Left) */}
        <div
          className="landing-solid-card absolute top-[272px] left-[20px] w-[180px] shadow-2xl border border-border p-4 rounded-xl z-30 transition-all duration-300 bg-secondary"
          style={{
            transform: `translateZ(${isHovered ? "70px" : "0px"})`,
            boxShadow: isHovered
              ? `${shadowX * 1.5}px ${shadowY * 1.5}px 45px -10px rgba(0, 0, 0, 0.3)`
              : "0 12px 24px -10px rgba(0, 0, 0, 0.2)",
          }}
        >
          <div className="flex items-center gap-1.5 border-b border-border/60 pb-2 mb-2.5 shrink-0">
            <span className="w-2 h-2 rounded bg-primary animate-pulse" />
            <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">
              Technical Performance
            </span>
          </div>
          <div className="space-y-2 text-[8.5px] font-mono text-foreground/70">
            <div className="flex justify-between items-center border-b border-border/30 pb-1">
              <span>Sys Design:</span>
              <span className="text-primary font-semibold">91%</span>
            </div>
            <div className="flex justify-between items-center border-b border-border/30 pb-1">
              <span>Migration:</span>
              <span className="text-primary font-semibold">Robust</span>
            </div>
            <div className="flex justify-between items-center">
              <span>DB Arch:</span>
              <span className="text-foreground/50 font-semibold">O(1) Reads</span>
            </div>
          </div>
        </div>

        {/* 4. Output Card B: Interview Performance (Bottom-Right) */}
        <div
          className="landing-solid-card absolute top-[272px] right-[20px] w-[185px] shadow-2xl border border-border p-4 rounded-xl z-30 transition-all duration-300"
          style={{
            transform: `translateZ(${isHovered ? "60px" : "0px"})`,
            boxShadow: isHovered
              ? `${shadowX * 1.2}px ${shadowY * 1.2}px 40px -10px rgba(0, 0, 0, 0.18), 0 0 0 1px rgba(var(--foreground), 0.05)`
              : "0 12px 24px -10px rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(var(--foreground), 0.03)",
          }}
        >
          <div className="flex items-center gap-1.5 border-b border-border/80 pb-2 mb-2.5 shrink-0">
            <span className="w-2 h-2 rounded bg-primary animate-pulse" />
            <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">
              Interview Performance
            </span>
          </div>
          <div className="space-y-2 text-[8.5px] font-medium text-foreground/80">
            <div className="flex justify-between items-center border-b border-border/40 pb-1">
              <span>Pacing:</span>
              <span className="text-primary font-bold">132 WPM</span>
            </div>
            <div className="flex justify-between items-center border-b border-border/40 pb-1">
              <span>Clarity:</span>
              <span className="text-primary font-bold">88% (Ideal)</span>
            </div>
            <div className="flex justify-between items-center">
              <span>Structure:</span>
              <span className="text-muted-foreground font-semibold">Cohesive</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function HeroSection({ onGetStarted, theme }: HeroSectionProps) {
  return (
    <section className="relative flex flex-col items-center overflow-visible border-b border-border/20 px-6 pb-12 pt-[136px] md:pb-20 md:pt-[152px]">
      <div className="relative z-10 mx-auto flex min-h-[calc(100dvh-152px)] w-full max-w-6xl flex-col justify-center">
        <div className="grid grid-cols-1 lg:grid-cols-[0.9fr_1.1fr] gap-12 lg:gap-20 items-center w-full">
          {/* Left */}
          <div className="flex flex-col items-start text-left max-w-xl">
            <h1
              className="text-5xl sm:text-6xl md:text-7xl lg:text-[4.9rem] font-semibold tracking-[-0.04em] leading-[1.02] text-foreground"
              style={{
                color: theme === "dark" ? "#FFFFFF" : "#000000",
                WebkitTextFillColor: theme === "dark" ? "#FFFFFF" : "#000000",
              }}
            >
              Practice your next interview before it happens.
            </h1>

            <p
              className="mt-6 text-base sm:text-lg lg:text-[1.2rem] text-muted-foreground font-normal leading-[1.7]"
              style={{
                color: theme === "dark" ? "#D4D4D8" : "#000000",
                WebkitTextFillColor: theme === "dark" ? "#D4D4D8" : "#000000",
              }}
            >
              Paste your resume and the job description. Run a live voice Interview Round calibrated to that role, then practise coding and system design in the separate Technical Round.
            </p>

            <div
              className="mt-8"
            >
              <button
                onClick={onGetStarted}
                className="h-12 rounded-lg bg-primary px-8 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/25 premium-transition hover:scale-[1.025] hover:shadow-xl hover:shadow-primary/30 hover:brightness-110 active:scale-[0.985] cursor-pointer"
              >
                Create Account to Start
              </button>
            </div>
          </div>

          {/* Right */}
          <div
            className="flex justify-center lg:justify-end lg:translate-x-6"
          >
            <IntegratedRealityGraphic />
          </div>
        </div>
      </div>
    </section>
  )
}
