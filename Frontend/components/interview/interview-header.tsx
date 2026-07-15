"use client"
import { User } from "lucide-react"
interface InterviewHeaderProps {
  mode: string
  showNav?: boolean
  showTimer?: boolean
}
export function InterviewHeader({ mode, showTimer = false }: InterviewHeaderProps) {
  const modeLabel = {
    "mock-ai": "Mock Interview Mode",
    "mock-voice": "Mock Interview Mode",
  }[mode] || "Interview"
  return (
    <nav className="fixed top-0 w-full z-50 bg-[var(--iv-surface)]/80 backdrop-blur-xl flex justify-between items-center px-8 h-16 border-b border-[var(--iv-outline-variant)]/10">
      <div className="flex items-center gap-8">
        {showTimer && (
          <div className="flex items-center gap-2 px-3 py-1 bg-[var(--iv-surface-container-high)] rounded-lg border border-[var(--iv-outline-variant)]/20">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--iv-error)] animate-pulse" />
            <span className="text-xs font-mono text-[var(--iv-on-surface)]/80">14:02</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-4">
        <span className="text-xs font-medium text-[var(--iv-on-surface)]/60 hidden sm:block">{modeLabel}</span>
        <div className="h-8 w-8 rounded-full bg-[var(--iv-surface-container-high)] flex items-center justify-center overflow-hidden border border-[var(--iv-outline-variant)]/20">
          <User className="h-4 w-4 text-[var(--iv-on-surface-variant)]" />
        </div>
      </div>
    </nav>
  )
}
