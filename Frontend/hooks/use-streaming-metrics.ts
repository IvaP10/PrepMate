"use client"

import { useState, useRef, useCallback, useEffect } from "react"

interface StreamingMetrics {
  engagement: { value: number; label: string }
  cameraContact: { value: number; label: string }
  pace: { wpm: number; label: string }
  dynamicTip: string | null
}

interface MetricsConfig {
  onMetricsUpdate?: (metrics: StreamingMetrics) => void
}

const DEFAULT_METRICS: StreamingMetrics = {
  engagement: { value: 50, label: "Moderate" },
  cameraContact: { value: 50, label: "Optimal" },
  pace: { wpm: 0, label: "-" },
  dynamicTip: null,
}

export function useStreamingMetrics(config: MetricsConfig = {}) {
  const [metrics, setMetrics] = useState<StreamingMetrics>(DEFAULT_METRICS)
  const wordCountRef = useRef(0)
  const speechStartRef = useRef<number | null>(null)
  const responseTimesRef = useRef<number[]>([])
  const lastUpdateRef = useRef(0)
  const updateIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const updateEngagement = useCallback(
    (responseTimeMs: number, vocalConfidence: number = 0.7) => {
      responseTimesRef.current.push(responseTimeMs)
      if (responseTimesRef.current.length > 10)
        responseTimesRef.current.shift()

      const avgResponseTime =
        responseTimesRef.current.reduce((a, b) => a + b, 0) /
        responseTimesRef.current.length

      let engagement = 50
      if (avgResponseTime < 2000) engagement += 25
      else if (avgResponseTime < 4000) engagement += 15
      else if (avgResponseTime < 6000) engagement += 5
      else engagement -= 10

      engagement += vocalConfidence * 25
      engagement = Math.max(0, Math.min(100, Math.round(engagement)))

      let label = "Moderate"
      if (engagement >= 80) label = "High"
      else if (engagement >= 60) label = "Good"
      else if (engagement < 40) label = "Low"

      setMetrics((prev) => ({
        ...prev,
        engagement: { value: engagement, label },
      }))
    },
    []
  )

  const updateCameraContact = useCallback(
    (eyeContactScore: number, contactLevel: string) => {
      setMetrics((prev) => ({
        ...prev,
        cameraContact: {
          value: Math.max(0, Math.min(100, eyeContactScore)),
          label: contactLevel,
        },
      }))
    },
    []
  )

  const addTranscriptWords = useCallback((text: string) => {
    const words = text.trim().split(/\s+/).filter(Boolean).length
    wordCountRef.current += words

    if (!speechStartRef.current) {
      speechStartRef.current = Date.now()
    }
  }, [])

  const calculateWPM = useCallback(() => {
    if (!speechStartRef.current || wordCountRef.current === 0) {
      return { wpm: 0, label: "-" }
    }

    const elapsedMinutes = (Date.now() - speechStartRef.current) / 60000
    if (elapsedMinutes < 0.05) return { wpm: 0, label: "Starting..." }

    const wpm = Math.round(wordCountRef.current / elapsedMinutes)

    let label = "Balanced"
    if (wpm < 80) label = "Slow"
    else if (wpm < 120) label = "Measured"
    else if (wpm < 160) label = "Balanced"
    else if (wpm < 200) label = "Fast"
    else label = "Too Fast"

    return { wpm, label }
  }, [])

  const setDynamicTip = useCallback((tip: string | null) => {
    setMetrics((prev) => ({ ...prev, dynamicTip: tip }))
  }, [])

  const resetSpeechTracking = useCallback(() => {
    wordCountRef.current = 0
    speechStartRef.current = null
  }, [])

  useEffect(() => {
    updateIntervalRef.current = setInterval(() => {
      const pace = calculateWPM()
      setMetrics((prev) => {
        const updated = { ...prev, pace }
        config.onMetricsUpdate?.(updated)
        return updated
      })
    }, 500)

    return () => {
      if (updateIntervalRef.current)
        clearInterval(updateIntervalRef.current)
    }
  }, [calculateWPM, config])

  return {
    metrics,
    updateEngagement,
    updateCameraContact,
    addTranscriptWords,
    setDynamicTip,
    resetSpeechTracking,
  }
}
