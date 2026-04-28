"use client"

import { useState, useRef, useCallback, useEffect } from "react"

/**
 * Cheap client-side check for whether the user's face is roughly centered.
 * NOT a real ML model — just samples pixel brightness and skin-tone regions
 * from a downscaled canvas to fill the gap between server-side MediaPipe ticks.
 */

interface FaceMetrics {
  facePresent: boolean
  centered: boolean
  engagementScore: number
  cameraContactLevel: "Low" | "Optimal" | "High"
}

const DEFAULTS: FaceMetrics = {
  facePresent: false,
  centered: false,
  engagementScore: 50,
  cameraContactLevel: "Optimal",
}

export function useFaceCheck(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const [metrics, setMetrics] = useState<FaceMetrics>(DEFAULTS)
  const [isRunning, setIsRunning] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const animFrameRef = useRef<number | null>(null)
  const lastProcessTime = useRef(0)

  const analyzeFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return

    const video = videoRef.current
    const canvas = canvasRef.current
    const ctx = canvas.getContext("2d")
    if (!ctx || video.readyState < 2) return

    const now = performance.now()
    if (now - lastProcessTime.current < 100) return
    lastProcessTime.current = now

    canvas.width = 120
    canvas.height = 90
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const data = imageData.data

    const centerX = canvas.width / 2
    const centerY = canvas.height / 2
    let skinCount = 0
    let skinXSum = 0
    let skinYSum = 0
    let totalSampled = 0

    for (let i = 0; i < data.length; i += 64) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      totalSampled++

      if (r > 60 && g > 40 && b > 20 && r > g && r > b && r - g > 15) {
        const pixelIndex = i / 4
        skinXSum += pixelIndex % canvas.width
        skinYSum += Math.floor(pixelIndex / canvas.width)
        skinCount++
      }
    }

    const facePresent = skinCount > 8
    let centered = false
    let engagement = 40

    if (facePresent) {
      const avgX = skinXSum / skinCount
      const avgY = skinYSum / skinCount
      const xOff = Math.abs(avgX - centerX) / centerX
      const yOff = Math.abs(avgY - centerY) / centerY

      centered = xOff < 0.25 && yOff < 0.3
      engagement = centered ? 70 : 45
    }

    let cameraContactLevel: FaceMetrics["cameraContactLevel"] = "Optimal"
    if (engagement < 40) cameraContactLevel = "Low"
    else if (engagement > 80) cameraContactLevel = "High"

    setMetrics({ facePresent, centered, engagementScore: engagement, cameraContactLevel })
  }, [videoRef])

  const start = useCallback(() => {
    if (isRunning) return
    if (!canvasRef.current) {
      canvasRef.current = document.createElement("canvas")
    }
    setIsRunning(true)

    const loop = () => {
      analyzeFrame()
      animFrameRef.current = requestAnimationFrame(loop)
    }
    loop()
  }, [isRunning, analyzeFrame])

  const stop = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
      animFrameRef.current = null
    }
    setIsRunning(false)
    setMetrics(DEFAULTS)
  }, [])

  useEffect(() => {
    return () => { stop() }
  }, [stop])

  return { metrics, isRunning, start, stop }
}
