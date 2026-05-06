"use client"

import { useState, useRef, useCallback, useEffect } from "react"

interface FaceMetrics {
  facePresent: boolean
  centered: boolean
  engagementScore: number
  cameraContactLevel: "Low" | "Optimal" | "High"
  posture?: string
  fidgetLevel?: "low" | "medium" | "high" | "unknown"
}

const DEFAULTS: FaceMetrics = {
  facePresent: false,
  centered: false,
  engagementScore: 50,
  cameraContactLevel: "Optimal",
  posture: "unknown",
  fidgetLevel: "unknown",
}

const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"

export function useFaceCheck(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const [metrics, setMetrics] = useState<FaceMetrics>(DEFAULTS)
  const [isRunning, setIsRunning] = useState(false)
  const animFrameRef = useRef<number | null>(null)
  const lastProcessTime = useRef(0)
  const landmarkerRef = useRef<any>(null)
  const loadingRef = useRef(false)
  const failedRef = useRef(false)
  const prevNoseRef = useRef<{ x: number; y: number } | null>(null)

  const loadLandmarker = useCallback(async () => {
    if (landmarkerRef.current || loadingRef.current || failedRef.current) return landmarkerRef.current
    loadingRef.current = true
    try {
      const vision = await import("@mediapipe/tasks-vision")
      const fileset = await vision.FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm"
      )
      landmarkerRef.current = await vision.FaceLandmarker.createFromOptions(fileset, {
        baseOptions: {
          modelAssetPath: MODEL_URL,
          delegate: "GPU",
        },
        runningMode: "VIDEO",
        numFaces: 1,
        outputFaceBlendshapes: false,
        outputFacialTransformationMatrixes: false,
      })
    } catch {
      failedRef.current = true
    } finally {
      loadingRef.current = false
    }
    return landmarkerRef.current
  }, [])

  const analyzeWithFallback = useCallback((video: HTMLVideoElement): FaceMetrics => {
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
    if (!facePresent) return DEFAULTS
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
    }
  }, [])

  const analyzeFrame = useCallback(async () => {
    const video = videoRef.current
    if (!video || video.readyState < 2) return

    const now = performance.now()
    if (now - lastProcessTime.current < 200) return
    lastProcessTime.current = now

    const landmarker = await loadLandmarker()
    if (!landmarker) {
      setMetrics(analyzeWithFallback(video))
      return
    }

    try {
      const result = landmarker.detectForVideo(video, now)
      const face = result.faceLandmarks?.[0]
      if (!face) {
        setMetrics(DEFAULTS)
        return
      }

      const nose = face[1]
      const chin = face[152]
      const left = face[234]
      const right = face[454]
      const xOff = Math.abs(nose.x - 0.5)
      const yOff = Math.abs(nose.y - 0.46)
      const centered = xOff < 0.13 && yOff < 0.18
      const yaw = Math.abs((right.x - left.x) - 0.32)
      const pitch = Math.abs((chin.y - nose.y) - 0.18)
      const posture = yaw < 0.12 && pitch < 0.13 ? "straight" : "slightly_off"

      const prev = prevNoseRef.current
      prevNoseRef.current = { x: nose.x, y: nose.y }
      const movement = prev ? Math.abs(prev.x - nose.x) + Math.abs(prev.y - nose.y) : 0
      const fidgetLevel = movement > 0.04 ? "high" : movement > 0.02 ? "medium" : "low"

      let engagement = 52
      if (centered) engagement += 24
      if (posture === "straight") engagement += 16
      if (fidgetLevel === "high") engagement -= 15
      else if (fidgetLevel === "medium") engagement -= 6
      engagement = Math.max(0, Math.min(100, engagement))

      let cameraContactLevel: FaceMetrics["cameraContactLevel"] = "Optimal"
      if (engagement < 50) cameraContactLevel = "Low"
      if (engagement > 86) cameraContactLevel = "High"

      setMetrics({
        facePresent: true,
        centered,
        engagementScore: engagement,
        cameraContactLevel,
        posture,
        fidgetLevel,
      })
    } catch {
      setMetrics(analyzeWithFallback(video))
    }
  }, [analyzeWithFallback, loadLandmarker, videoRef])

  const start = useCallback(() => {
    if (isRunning) return
    setIsRunning(true)
    const loop = () => {
      void analyzeFrame()
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
    return () => {
      stop()
      landmarkerRef.current?.close?.()
    }
  }, [stop])

  return { metrics, isRunning, start, stop }
}
