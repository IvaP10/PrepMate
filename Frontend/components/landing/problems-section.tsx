"use client"
import { useState, useRef } from "react"
import { ChevronDown } from "lucide-react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"
const features = [
  {
    title: "Customized questions derived directly from your experience.",
    description:
      "Our system analyzes your resume to generate targeted questions based on your unique skills, projects, and professional background, ensuring highly relevant practice.",
  },
  {
    title: "Comprehensive, actionable feedback.",
    description:
      "Following each response, receive detailed insights into your performance. We evaluate your answers for clarity, depth, and strategic alignment with the question asked.",
  },
  {
    title: "Flexible practice on your own schedule.",
    description:
      "Eliminate scheduling conflicts. Conduct simulated practice sessions at any time, from anywhere, ensuring you are consistently prepared for your next opportunity.",
  },
  {
    title: "Track your progress and measurable improvement.",
    description:
      "Monitor your performance metrics over time. Identify areas for improvement and leverage detailed analytics to refine your interviewing strategy.",
  },
]
export function ProblemsSection() {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0)
  const { ref: headerRef, isVisible: isHeaderVisible } = useScrollReveal({ threshold: 0.15 })
  return (
    <section id="features" className="relative px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <div ref={headerRef} className="mx-auto mb-6 max-w-2xl text-center">
          <span className={`mb-4 inline-block text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground ${isHeaderVisible ? 'animate-fade-in-up' : 'opacity-0'}`}>
            Features
          </span>
          <h2 className="text-balance font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl md:text-5xl">
            <span className={`text-shimmer inline-block ${isHeaderVisible ? 'animate-blur-in delay-100' : 'opacity-0'}`}>Engineered for effective</span>
            <br />
            <span className={`text-shimmer inline-block ${isHeaderVisible ? 'animate-blur-in delay-200' : 'opacity-0'}`}>interview </span>{" "}
            <span className={`text-shimmer-accent inline-block ${isHeaderVisible ? 'animate-blur-in delay-300' : 'opacity-0'}`}>preparation.</span>
          </h2>
          <p className={`mt-5 text-lg text-muted-foreground ${isHeaderVisible ? 'animate-fade-in-up delay-500' : 'opacity-0'}`}>
            Streamlined and purpose-built. Every feature is meticulously designed to accelerate your career advancement.
          </p>
        </div>
        <div className="mt-16 grid grid-cols-1 items-start gap-12 lg:grid-cols-2">
          <div className="flex flex-col">
            {features.map((feature, i) => {
              const isOpen = expandedIndex === i
              return (
                <div key={i} className="group border-b border-border transition-colors duration-300 hover:border-accent-indigo/20">
                  <button
                    type="button"
                    onClick={() => setExpandedIndex(isOpen ? null : i)}
                    className="flex w-full items-center justify-between py-5 text-left transition-all duration-300 hover:pl-1"
                  >
                    <span
                      className={`text-base font-medium transition-colors duration-300 ${isOpen ? "text-foreground" : "text-muted-foreground group-hover:text-foreground"
                        }`}
                    >
                      {feature.title}
                    </span>
                    <ChevronDown
                      className={`ml-4 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ${isOpen ? "rotate-180" : ""
                        }`}
                    />
                  </button>
                  <div
                    className={`overflow-hidden transition-all duration-300 ${isOpen ? "max-h-60 pb-5" : "max-h-0"
                      }`}
                  >
                    <div className="rounded-xl border border-border bg-card p-5">
                      <p className="text-base leading-relaxed text-muted-foreground">
                        {feature.description}
                      </p>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="hidden overflow-hidden rounded-2xl border border-border/40 bg-card shadow-[0_12px_40px_-15px_rgba(37,99,235,0.12)] transition-all duration-500 ease-out hover:-translate-y-2 lg:block">
            <div className="border-b border-border/40 p-6 bg-card/50">
              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-green-500"></span> InterAI Dashboard
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">Review your historical sessions and comprehensive performance data.</p>
            </div>
            <div className="bg-background overflow-hidden p-6">
              <div className="rounded-xl border border-border/40 bg-card">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/40 bg-secondary/20">
                      <th className="px-4 py-3 text-left font-medium text-muted-foreground">Date</th>
                      <th className="px-4 py-3 text-left font-medium text-muted-foreground">Role</th>
                      <th className="px-4 py-3 text-left font-medium text-muted-foreground">Score</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    <tr className="hover:bg-secondary/10 transition-colors">
                      <td className="px-4 py-3 text-foreground whitespace-nowrap">Today, 10:00 AM</td>
                      <td className="px-4 py-3 text-foreground font-medium">Software Engineer</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
                            <div className="h-full rounded-full bg-green-500" style={{ width: '86%' }} />
                          </div>
                          <span className="text-xs font-semibold text-foreground">86%</span>
                        </div>
                      </td>
                    </tr>
                    <tr className="hover:bg-secondary/10 transition-colors">
                      <td className="px-4 py-3 text-foreground whitespace-nowrap">Yesterday</td>
                      <td className="px-4 py-3 text-foreground font-medium">Frontend Developer</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
                            <div className="h-full rounded-full bg-amber-500" style={{ width: '72%' }} />
                          </div>
                          <span className="text-xs font-semibold text-foreground">72%</span>
                        </div>
                      </td>
                    </tr>
                    <tr className="hover:bg-secondary/10 transition-colors">
                      <td className="px-4 py-3 text-foreground whitespace-nowrap">Mar 4, 2026</td>
                      <td className="px-4 py-3 text-foreground font-medium">Backend Developer</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
                            <div className="h-full rounded-full bg-green-500" style={{ width: '91%' }} />
                          </div>
                          <span className="text-xs font-semibold text-foreground">91%</span>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
