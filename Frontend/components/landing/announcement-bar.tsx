"use client"
import { useState } from "react"
import { X } from "lucide-react"

interface AnnouncementBarProps {
  onDismiss?: () => void
}

export function AnnouncementBar({ onDismiss }: AnnouncementBarProps) {
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  const handleDismiss = () => {
    setDismissed(true)
    onDismiss?.()
  }

  return (
    <div className="relative w-full flex h-10 items-center justify-center gap-2 border-b border-border/40 bg-secondary/80 px-4 pr-10 text-center backdrop-blur-sm">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-20 announcement-shimmer"
          style={{
            background: "linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.12) 50%, transparent 100%)",
          }}
        />
      </div>

      <p className="relative text-[11px] sm:text-xs font-semibold text-foreground/80 tracking-wide">
        <span className="font-bold">Early Bird Offer</span>
        <span className="mx-1.5 text-foreground/30">·</span>
        <span className="text-foreground/60">Register by 31 August 2026 to get Premium free for 30 days</span>
      </p>

      <button
        onClick={handleDismiss}
        className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-foreground/40 transition-all hover:bg-secondary hover:text-foreground/70 cursor-pointer"
        aria-label="Dismiss announcement"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
