/**
 * useAudioEnvironment — Detect background audio (music, calls, etc.)
 * using the Web Audio API's AnalyserNode on the local microphone stream.
 *
 * How it works:
 * - Monitors the frequency spectrum of the microphone input
 * - Music/calls produce sustained energy across mid-to-high frequency bands
 *   with low variance, while speech is intermittent with high variance
 * - Triggers a callback when persistent background audio is detected
 */

import { useCallback, useEffect, useRef } from "react"

interface AudioEnvironmentOptions {
  /** Called when background audio (music, call, etc.) is detected */
  onBackgroundAudioDetected?: (details: { type: string; confidence: number }) => void
  /** How often to check, in ms. Default 2000 */
  checkIntervalMs?: number
  /** Minimum seconds of sustained background audio before triggering. Default 4 */
  sustainedThresholdSeconds?: number
  /** Whether detection is active. Default true */
  enabled?: boolean
}

export function useAudioEnvironment(
  stream: MediaStream | null,
  options: AudioEnvironmentOptions = {}
) {
  const {
    onBackgroundAudioDetected,
    checkIntervalMs = 2000,
    sustainedThresholdSeconds = 4,
    enabled = true,
  } = options

  const analyserRef = useRef<AnalyserNode | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sustainedCountRef = useRef(0)
  const lastAlertRef = useRef(0)
  const callbackRef = useRef(onBackgroundAudioDetected)

  useEffect(() => {
    callbackRef.current = onBackgroundAudioDetected
  }, [onBackgroundAudioDetected])

  const cleanup = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    sourceRef.current?.disconnect()
    sourceRef.current = null
    analyserRef.current?.disconnect()
    analyserRef.current = null
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      void audioCtxRef.current.close().catch(() => {})
    }
    audioCtxRef.current = null
    sustainedCountRef.current = 0
  }, [])

  useEffect(() => {
    if (!enabled || !stream) {
      cleanup()
      return
    }

    const audioTracks = stream.getAudioTracks()
    if (audioTracks.length === 0) return

    try {
      const audioCtx = new AudioContext()
      audioCtxRef.current = audioCtx

      const source = audioCtx.createMediaStreamSource(stream)
      sourceRef.current = source

      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.8
      analyserRef.current = analyser

      source.connect(analyser)
      // Don't connect to destination — we only analyze, don't play back

      const frequencyData = new Uint8Array(analyser.frequencyBinCount)
      const checksNeeded = Math.ceil((sustainedThresholdSeconds * 1000) / checkIntervalMs)

      intervalRef.current = setInterval(() => {
        if (!analyserRef.current) return

        analyserRef.current.getByteFrequencyData(frequencyData)

        // Split frequency spectrum into bands
        const binCount = frequencyData.length
        const lowEnd = Math.floor(binCount * 0.05) // Skip very low (DC, hum)
        const midStart = Math.floor(binCount * 0.1)
        const midEnd = Math.floor(binCount * 0.5)
        const highStart = Math.floor(binCount * 0.5)
        const highEnd = Math.floor(binCount * 0.8)

        // Calculate average energy in different bands
        let lowEnergy = 0
        for (let i = lowEnd; i < midStart; i++) lowEnergy += frequencyData[i]
        lowEnergy /= Math.max(1, midStart - lowEnd)

        let midEnergy = 0
        for (let i = midStart; i < midEnd; i++) midEnergy += frequencyData[i]
        midEnergy /= Math.max(1, midEnd - midStart)

        let highEnergy = 0
        for (let i = highStart; i < highEnd; i++) highEnergy += frequencyData[i]
        highEnergy /= Math.max(1, highEnd - highStart)

        // Calculate overall energy
        let totalEnergy = 0
        for (let i = lowEnd; i < highEnd; i++) totalEnergy += frequencyData[i]
        totalEnergy /= Math.max(1, highEnd - lowEnd)

        // Music/calls have these characteristics vs speech:
        // 1. Sustained mid+high frequency energy (speech is intermittent)
        // 2. Relatively smooth spectrum (speech has formant peaks)
        // 3. Energy present even during "silence" periods

        // Calculate spectral flatness (music is more flat, speech has peaks)
        let specSum = 0
        let specLogSum = 0
        let specCount = 0
        for (let i = midStart; i < highEnd; i++) {
          const val = Math.max(1, frequencyData[i])
          specSum += val
          specLogSum += Math.log(val)
          specCount++
        }
        const geometricMean = Math.exp(specLogSum / specCount)
        const arithmeticMean = specSum / specCount
        const spectralFlatness = geometricMean / Math.max(1, arithmeticMean)

        // Background audio indicators:
        // - Total energy above threshold (something is playing)
        // - Mid + high energy relatively balanced (music has wide spectrum)
        // - Spectral flatness higher than speech
        const hasSignificantEnergy = totalEnergy > 20
        const hasBroadSpectrum = midEnergy > 15 && highEnergy > 10
        const isMusicLike = spectralFlatness > 0.35
        const isBackgroundAudio = hasSignificantEnergy && hasBroadSpectrum && isMusicLike

        if (isBackgroundAudio) {
          sustainedCountRef.current++
        } else {
          // Reset slowly (allow brief dips)
          sustainedCountRef.current = Math.max(0, sustainedCountRef.current - 1)
        }

        if (sustainedCountRef.current >= checksNeeded) {
          const now = Date.now()
          // Don't alert more than once every 30 seconds
          if (now - lastAlertRef.current > 30000) {
            lastAlertRef.current = now
            const confidence = Math.min(
              100,
              Math.round(
                (spectralFlatness * 100 + totalEnergy) / 2
              )
            )
            callbackRef.current?.({
              type: isMusicLike ? "background_music" : "background_audio",
              confidence,
            })
          }
          sustainedCountRef.current = checksNeeded // Cap it
        }
      }, checkIntervalMs)
    } catch {
      // Web Audio API not available — fail silently
    }

    return cleanup
  }, [stream, enabled, checkIntervalMs, sustainedThresholdSeconds, cleanup])

  return { cleanup }
}
