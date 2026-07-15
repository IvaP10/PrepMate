"use client"

import { useState, useRef, useCallback, useEffect } from "react"

export interface ObjectMetrics {
  mobileDetected: boolean
  multiplePeopleDetected: boolean
}

const DEFAULTS: ObjectMetrics = {
  mobileDetected: false,
  multiplePeopleDetected: false,
}

const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite"

export function useObjectDetection(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const [metrics, setMetrics] = useState<ObjectMetrics>(DEFAULTS)
  const [isRunning, setIsRunning] = useState(false)
  const intervalRef = useRef<any>(null)
  const lastProcessTime = useRef(0)
  const detectorRef = useRef<any>(null)
  const loadingRef = useRef(false)
  const failedRef = useRef(false)
  const repeatedHitsRef = useRef({ mobile: 0, people: 0 })

  const loadDetector = useCallback(async () => {
    if (detectorRef.current || loadingRef.current || failedRef.current) return detectorRef.current
    loadingRef.current = true
    try {
      const vision = await import("@mediapipe/tasks-vision")
      const fileset = await vision.FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm"
      )
      detectorRef.current = await vision.ObjectDetector.createFromOptions(fileset, {
        baseOptions: {
          modelAssetPath: MODEL_URL,
          delegate: "GPU",
        },
        runningMode: "VIDEO",
        scoreThreshold: 0.5,
      })
    } catch {
      failedRef.current = true
    } finally {
      loadingRef.current = false
    }
    return detectorRef.current
  }, [])

  const analyzeFrame = useCallback(async () => {
    const video = videoRef.current
    if (!video || video.readyState < 2) return

    const now = performance.now()
    if (now - lastProcessTime.current < 1000) return // Limit detection frequency to 1FPS to save power
    lastProcessTime.current = now

    const detector = await loadDetector()
    if (!detector) return

    try {
      const result = detector.detectForVideo(video, now)
      
      let mobileDetected = false
      let personCount = 0

      if (result.detections) {
        for (const detection of result.detections) {
          for (const category of detection.categories) {
            if (category.categoryName === "cell phone" && category.score > 0.5) {
               mobileDetected = true
            }
            if (category.categoryName === "person" && category.score > 0.5) {
               personCount++
            }
          }
        }
      }

      repeatedHitsRef.current = {
        mobile: mobileDetected ? repeatedHitsRef.current.mobile + 1 : 0,
        people: personCount > 1 ? repeatedHitsRef.current.people + 1 : 0,
      }
      setMetrics({
        mobileDetected: repeatedHitsRef.current.mobile >= 2,
        multiplePeopleDetected: repeatedHitsRef.current.people >= 2,
      })
    } catch {
      repeatedHitsRef.current = { mobile: 0, people: 0 }
      setMetrics(DEFAULTS)
    }
  }, [loadDetector, videoRef])

  const start = useCallback(() => {
    if (isRunning) return
    setIsRunning(true)
    intervalRef.current = setInterval(() => {
      void analyzeFrame()
    }, 1000)
  }, [isRunning, analyzeFrame])

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setIsRunning(false)
    repeatedHitsRef.current = { mobile: 0, people: 0 }
    setMetrics(DEFAULTS)
  }, [])

  useEffect(() => {
    return () => {
      stop()
      try {
        detectorRef.current?.close?.()
      } catch {
        // ignore close errors
      }
    }
  }, [stop])

  return { metrics, isRunning, start, stop }
}
