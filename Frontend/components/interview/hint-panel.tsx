"use client"
import { useState, useEffect } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"
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
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-secondary transition-colors"
      >
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">Suggestions</h3>
          {displayedHints.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-semibold">
              {displayedHints.length}
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        )}
      </button>
      {isExpanded && (
        <div className="px-4 pb-3 space-y-2">
          {displayedHints.map((hint, i) => (
            <div
              key={i}
              className="p-2.5 rounded-lg bg-secondary border border-border animate-in fade-in slide-in-from-bottom-1 duration-300"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <p className="text-xs text-muted-foreground leading-relaxed">{hint}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
