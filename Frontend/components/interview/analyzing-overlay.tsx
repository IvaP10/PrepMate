"use client"
import { useEffect, useState } from "react"
import { API_CONFIG } from "@/lib/config"
interface AnalyzingOverlayProps {
  isVisible: boolean
  interviewId?: string
  onComplete?: () => void
  onPollComplete?: () => void
}
export function AnalyzingOverlay({
  isVisible,
  interviewId,
  onComplete,
  onPollComplete,
}: AnalyzingOverlayProps) {
  const [progress, setProgress] = useState(0)
  const [statusText, setStatusText] = useState("Gathering responses...")
  const [dots, setDots] = useState("")
  useEffect(() => {
    if (!isVisible) return
    const dotInterval = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? "" : prev + "."))
    }, 400)
    const stages = [
      { at: 10, text: "Gathering responses" },
      { at: 25, text: "Analyzing verbal patterns" },
      { at: 40, text: "Processing nonverbal cues" },
      { at: 55, text: "Evaluating technical depth" },
      { at: 70, text: "Calculating performance scores" },
      { at: 85, text: "Generating detailed feedback" },
      { at: 95, text: "Finalizing report" },
    ]
    const progressInterval = setInterval(() => {
      setProgress((prev) => {
        const next = Math.min(prev + 0.8, 96)
        const stage = [...stages].reverse().find((s) => next >= s.at)
        if (stage) setStatusText(stage.text)
        return next
      })
    }, 100)
    return () => {
      clearInterval(dotInterval)
      clearInterval(progressInterval)
    }
  }, [isVisible])
  useEffect(() => {
    if (!isVisible || !interviewId) return
    const pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(
          `${API_CONFIG.BASE_URL}/interview/status/${interviewId}`,
          {
            credentials: "include",
          }
        )
        if (resp.ok) {
          const data = await resp.json()
          if (data.status === "completed" || data.completed_at) {
            setProgress(100)
            setStatusText("Report ready!")
            onPollComplete?.()
            clearInterval(pollInterval)
            setTimeout(() => {
              onComplete?.()
            }, 1200)
          }
        }
      } catch {
      }
    }, 2000)
    const fallbackTimeout = setTimeout(() => {
      setProgress(100)
      clearInterval(pollInterval)
      onComplete?.()
    }, 30000)
    return () => {
      clearInterval(pollInterval)
      clearTimeout(fallbackTimeout)
    }
  }, [isVisible, interviewId, onComplete, onPollComplete])
  if (!isVisible) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-xl">
      <div className="flex flex-col items-center gap-8 max-w-md w-full px-6">
        <div className="relative w-20 h-20">
          <svg className="w-full h-full animate-spin" viewBox="0 0 80 80">
            <circle
              cx="40"
              cy="40"
              r="35"
              fill="none"
              stroke="rgba(99, 102, 241, 0.15)"
              strokeWidth="4"
            />
            <circle
              cx="40"
              cy="40"
              r="35"
              fill="none"
              stroke="url(#gradient)"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={`${progress * 2.2} 220`}
              className="transition-all duration-300"
            />
            <defs>
              <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#6366f1" />
                <stop offset="50%" stopColor="#a855f7" />
                <stop offset="100%" stopColor="#ec4899" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-white/90 text-sm font-semibold tabular-nums">
              {Math.round(progress)}%
            </span>
          </div>
        </div>
        <div className="text-center space-y-2">
          <h2 className="text-2xl font-bold text-white">
            Analyzing Interview{dots}
          </h2>
          <p className="text-white/60 text-sm">{statusText}</p>
        </div>
        <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-white/30 text-xs">
          Please wait while we prepare your detailed feedback report
        </p>
      </div>
    </div>
  )
}
