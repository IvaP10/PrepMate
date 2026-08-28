"use client"

import { useState, useRef, useCallback, useEffect } from "react"

interface FaceMetrics {
  facePresent: boolean
  centered: boolean
  engagementScore: number
  cameraContactLevel: "Low" | "Optimal" | "High"
  posture?: string
  fidgetLevel?: "low" | "medium" | "high" | "unknown"
  source?: "local" | "unavailable"
}

const DEFAULTS: FaceMetrics = {
  facePresent: false,
  centered: false,
  engagementScore: 50,
  cameraContactLevel: "Optimal",
  posture: "unknown",
  fidgetLevel: "unknown",
  source: "unavailable",
}

export function useFaceCheck(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const [metrics, setMetrics] = useState<FaceMetrics>(DEFAULTS)
  const [isRunning, setIsRunning] = useState(false)
  const intervalRef = useRef<any>(null)
  const isRunningRef = useRef(false)
  const lastProcessTime = useRef(0)
  const analyzeLocally = useCallback((video: HTMLVideoElement): FaceMetrics => {
    const canvas = document.createElement("canvas")
    const ctx = canvas.getContext("2d")
    if (!ctx || video.readyState < 2) return DEFAULTS

    canvas.width = 120
    canvas.height = 90
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    let skinCount = 0
    let xSum = 0
    let ySum = 0
    for (let i = 0; i < data.length; i += 64) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      if (r > 60 && g > 40 && b > 20 && r > g && r > b && r - g > 15) {
        const pixelIndex = i / 4
        xSum += pixelIndex % canvas.width
        ySum += Math.floor(pixelIndex / canvas.width)
        skinCount++
      }
    }
    const facePresent = skinCount > 8
    if (!facePresent) return { ...DEFAULTS, source: "local" }
    const xOff = Math.abs(xSum / skinCount - canvas.width / 2) / (canvas.width / 2)
    const yOff = Math.abs(ySum / skinCount - canvas.height / 2) / (canvas.height / 2)
    const centered = xOff < 0.25 && yOff < 0.3
    const engagement = centered ? 70 : 45
    const cameraContactLevel: FaceMetrics["cameraContactLevel"] = engagement < 50 ? "Low" : "Optimal"
    return {
      facePresent,
      centered,
      engagementScore: engagement,
      cameraContactLevel,
      posture: centered ? "straight" : "off_center",
      fidgetLevel: "unknown" as const,
      source: "local",
    }
  }, [])

  const analyzeFrame = useCallback(async () => {
    const video = videoRef.current
    if (!video || video.readyState < 2) return

    const now = performance.now()
    if (now - lastProcessTime.current < 200) return
    lastProcessTime.current = now

    try {
      setMetrics(analyzeLocally(video))
    } catch {
      setMetrics(DEFAULTS)
    }
  }, [analyzeLocally, videoRef])

  const start = useCallback(() => {
    if (isRunningRef.current) return
    isRunningRef.current = true
    setIsRunning(true)
    intervalRef.current = setInterval(() => {
      void analyzeFrame()
    }, 250)
  }, [analyzeFrame])

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (!isRunningRef.current) return
    isRunningRef.current = false
    setIsRunning(false)
    setMetrics(DEFAULTS)
  }, [])

  useEffect(() => {
    return () => {
      stop()
    }
  }, [stop])

  return { metrics, isRunning, start, stop }
}
