"use client"
import { useEffect, useState, useRef } from "react"
import { useRouter } from "next/navigation"
import { API_CONFIG } from "@/lib/config"
import { getAuthHeaders } from "@/lib/auth"
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
  const router = useRouter()
  const [progress, setProgress] = useState(0)
  const [hasBackendProgress, setHasBackendProgress] = useState(false)
  const [statusText, setStatusText] = useState("Preparing your report…")
  const [dots, setDots] = useState("")
  const [showComeBackLater, setShowComeBackLater] = useState(false)
  const [keepWaiting, setKeepWaiting] = useState(false)
  const startTimeRef = useRef(Date.now())

  const onCompleteRef = useRef(onComplete)
  const onPollCompleteRef = useRef(onPollComplete)

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  useEffect(() => {
    onPollCompleteRef.current = onPollComplete
  }, [onPollComplete])

  useEffect(() => {
    if (!isVisible) return
    setProgress(0)
    setHasBackendProgress(false)
    setStatusText("Preparing your report…")
    setShowComeBackLater(false)
    setKeepWaiting(false)
  }, [isVisible, interviewId])

  // Dot animation
  useEffect(() => {
    if (!isVisible) return
    const dotInterval = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? "" : prev + "."))
    }, 400)
    return () => clearInterval(dotInterval)
  }, [isVisible])

  // Timeout: after 45s show "come back later" UI
  useEffect(() => {
    if (!isVisible) return
    startTimeRef.current = Date.now()
    const timeout = setTimeout(() => {
      if (!keepWaiting) {
        setShowComeBackLater(true)
      }
    }, 45000)
    return () => clearTimeout(timeout)
  }, [isVisible, keepWaiting])

  // Poll backend for real progress
  useEffect(() => {
    if (!isVisible || !interviewId) return
    let pollInterval: ReturnType<typeof setInterval> | undefined
    const pollStatus = async () => {
      try {
        const resp = await fetch(
          `${API_CONFIG.BASE_URL}/interview/${interviewId}/analysis-status`,
          {
            credentials: "include",
            headers: getAuthHeaders(),
          }
        )
        if (resp.ok) {
          const data = await resp.json()

          // Use real progress from backend if available
          if (typeof data.job?.progress === "number") {
            setProgress((prev) => Math.max(prev, data.job.progress))
            setHasBackendProgress(true)
          }

          if (data.report_ready) {
            setProgress(100)
            setStatusText("Report ready!")
            setShowComeBackLater(false)
            onPollCompleteRef.current?.()
            if (pollInterval) clearInterval(pollInterval)
            setTimeout(() => {
              onCompleteRef.current?.()
            }, 1200)
          } else if (data.status === "failed" || data.job?.status === "failed") {
            setStatusText(data.job?.error_message || "Analysis failed. Opening report status.")
            setShowComeBackLater(false)
            if (pollInterval) clearInterval(pollInterval)
            setTimeout(() => {
              onCompleteRef.current?.()
            }, 1200)
          } else {
            const backendStage = data.job?.current_stage?.replace(/_/g, " ")
            if (backendStage) setStatusText(backendStage)
            else setStatusText("Preparing your report…")
          }
        }
      } catch {
      }
    }
    void pollStatus()
    pollInterval = setInterval(() => void pollStatus(), 2000)
    return () => {
      clearInterval(pollInterval)
    }
  }, [isVisible, interviewId])

  if (!isVisible) return null

  // "Come back later" UI
  if (showComeBackLater && !keepWaiting) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 backdrop-blur-md">
        <div className="flex flex-col items-center gap-6 max-w-md w-full px-6">
          <div className="relative w-16 h-16">
            <div className="w-full h-full rounded-full bg-emerald-500/15 flex items-center justify-center">
              <svg className="w-8 h-8 text-emerald-500" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
          <div className="text-center space-y-3">
            <h2 className="text-2xl font-semibold text-foreground">
              Your interview has been submitted!
            </h2>
            <p className="text-muted-foreground text-sm leading-6">
              Your detailed report is still processing. You can return to it from Interview when it is ready.
            </p>
            <p className="text-muted-foreground text-sm leading-6">
              You can safely leave this page and check your report from Interview.
            </p>
          </div>
          <div className="flex flex-col gap-3 w-full sm:flex-row sm:justify-center">
            <button
              onClick={() => router.push("/?tab=interview")}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Go to Interview
            </button>
            <button
              onClick={() => {
                setKeepWaiting(true)
                setShowComeBackLater(false)
              }}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-6 py-2.5 text-sm font-medium text-foreground hover:bg-secondary/80 transition-colors"
            >
              Keep Waiting
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 backdrop-blur-md">
      <div className="flex flex-col items-center gap-8 max-w-md w-full px-6">
        <div className="relative w-20 h-20">
          <svg className="w-full h-full -rotate-90" viewBox="0 0 80 80">
            <circle
              cx="40"
              cy="40"
              r="35"
              fill="none"
              stroke="var(--border)"
              strokeWidth="4"
            />
            <circle
              cx="40"
              cy="40"
              r="35"
              fill="none"
              stroke="var(--primary)"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={`${progress * 2.2} 220`}
              className="transition-all duration-300"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            {hasBackendProgress ? (
              <span className="text-foreground text-sm font-semibold tabular-nums">{Math.round(progress)}%</span>
            ) : (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-label="Processing" />
            )}
          </div>
        </div>
        <div className="text-center space-y-2">
          <h2 className="text-2xl font-semibold text-foreground">
            Analyzing Interview{dots}
          </h2>
          <p className="text-muted-foreground text-sm">{statusText}</p>
        </div>
        {hasBackendProgress ? (
          <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-primary rounded-full transition-all duration-300 ease-out" style={{ width: `${progress}%` }} />
          </div>
        ) : (
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"><div className="h-full w-1/3 animate-pulse rounded-full bg-primary/70" /></div>
        )}
        <p className="text-muted-foreground text-xs">
          Please wait while we prepare your detailed feedback report
        </p>
      </div>
    </div>
  )
}
