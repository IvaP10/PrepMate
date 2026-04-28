"use client"
import { useState, useEffect } from "react"
import { Lightbulb, ChevronDown, ChevronUp, Sparkles } from "lucide-react"
interface HintPanelProps {
  hints: string[]
  isVisible?: boolean
}
export function HintPanel({ hints, isVisible = true }: HintPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true)
  const [displayedHints, setDisplayedHints] = useState<string[]>([])
  useEffect(() => {
    if (hints.length > displayedHints.length) {
      const newHints = hints.slice(displayedHints.length)
      newHints.forEach((hint, i) => {
        setTimeout(() => {
          setDisplayedHints((prev) => [...prev, hint])
        }, i * 200)
      })
    } else {
      setDisplayedHints(hints)
    }
  }, [hints])
  if (!isVisible || hints.length === 0) return null
  return (
    <div className="bg-white/[0.03] backdrop-blur-md rounded-xl border border-white/10 overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-amber-500/20 flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <h3 className="text-sm font-semibold text-white/80">AI Suggestions</h3>
          {displayedHints.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold">
              {displayedHints.length}
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-white/40" />
        ) : (
          <ChevronDown className="w-4 h-4 text-white/40" />
        )}
      </button>
      {isExpanded && (
        <div className="px-4 pb-3 space-y-2">
          {displayedHints.map((hint, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-2.5 rounded-lg bg-white/[0.02] border border-white/5 animate-in fade-in slide-in-from-bottom-1 duration-300"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <Lightbulb className="w-3.5 h-3.5 text-amber-400/70 mt-0.5 shrink-0" />
              <p className="text-xs text-white/60 leading-relaxed">{hint}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
