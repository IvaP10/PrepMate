"use client"

import { useState, useRef, useCallback, useEffect } from "react"

interface VADConfig {
  onSpeechStart?: () => void
  onSpeechEnd?: (duration: number) => void
  onVADMisfire?: () => void
  silenceThreshold?: number
  speechThreshold?: number
  minSpeechDuration?: number
}

interface VADState {
  isSpeaking: boolean
  isListening: boolean
  speechDuration: number
}

export function useVAD(config: VADConfig = {}) {
  const {
    silenceThreshold = -45,
    speechThreshold = -35,
    minSpeechDuration = 300,
  } = config

  const [state, setState] = useState<VADState>({
    isSpeaking: false,
    isListening: false,
    speechDuration: 0,
  })

  const analyserRef = useRef<AnalyserNode | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const animFrameRef = useRef<number | null>(null)
  const speechStartRef = useRef<number | null>(null)
  const silenceStartRef = useRef<number | null>(null)
  const isSpeakingRef = useRef(false)

  const startListening = useCallback(
    (stream: MediaStream) => {
      if (audioContextRef.current) return

      const audioCtx = new AudioContext()
      const source = audioCtx.createMediaStreamSource(stream)
      const analyser = audioCtx.createAnalyser()

      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.85
      source.connect(analyser)

      audioContextRef.current = audioCtx
      analyserRef.current = analyser

      const dataArray = new Float32Array(analyser.fftSize)

      const detect = () => {
        analyser.getFloatTimeDomainData(dataArray)

        let sum = 0
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i] * dataArray[i]
        }
        const rms = Math.sqrt(sum / dataArray.length)
        const db = 20 * Math.log10(Math.max(rms, 1e-10))

        const now = Date.now()

        if (db > speechThreshold) {
          silenceStartRef.current = null

          if (!isSpeakingRef.current) {
            speechStartRef.current = now
            isSpeakingRef.current = true
            setState((prev) => ({ ...prev, isSpeaking: true }))
            config.onSpeechStart?.()
          }
        } else if (db < silenceThreshold) {
          if (isSpeakingRef.current) {
            if (!silenceStartRef.current) {
              silenceStartRef.current = now
            }

            const silenceDuration = now - silenceStartRef.current
            if (silenceDuration > 600) {
              const spDuration = speechStartRef.current
                ? now - speechStartRef.current
                : 0

              if (spDuration >= minSpeechDuration) {
                isSpeakingRef.current = false
                setState((prev) => ({
                  ...prev,
                  isSpeaking: false,
                  speechDuration: spDuration,
                }))
                config.onSpeechEnd?.(spDuration)
              } else {
                isSpeakingRef.current = false
                setState((prev) => ({ ...prev, isSpeaking: false }))
                config.onVADMisfire?.()
              }

              speechStartRef.current = null
              silenceStartRef.current = null
            }
          }
        }

        animFrameRef.current = requestAnimationFrame(detect)
      }

      setState((prev) => ({ ...prev, isListening: true }))
      detect()
    },
    [config, silenceThreshold, speechThreshold, minSpeechDuration]
  )

  const stopListening = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
      animFrameRef.current = null
    }
    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }
    analyserRef.current = null
    isSpeakingRef.current = false
    speechStartRef.current = null
    silenceStartRef.current = null
    setState({ isSpeaking: false, isListening: false, speechDuration: 0 })
  }, [])

  useEffect(() => {
    return () => {
      stopListening()
    }
  }, [stopListening])

  return {
    ...state,
    startListening,
    stopListening,
  }
}
