"use client"
import { useState, useEffect, useRef, useCallback } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { Clock, MicOff, AlertTriangle } from "lucide-react"
import { InterviewControls } from "@/components/interview/interview-controls"
import { AnalyzingOverlay } from "@/components/interview/analyzing-overlay"
import { useVAD } from "@/hooks/use-vad"
import { useFaceCheck } from "@/hooks/use-face-check"
import { useStreamingMetrics } from "@/hooks/use-streaming-metrics"
import { useAudioEnvironment } from "@/hooks/use-audio-environment"
import { useSessionControlLock } from "@/hooks/use-session-control-lock"
import { getAuthHeaders } from "@/lib/auth"
import { API_CONFIG } from "@/lib/config"
import { abandonInterviewSession, cancelInterviewSession, endInterviewSession } from "@/lib/api"
import { readRecoveryGraceSeconds } from "@/lib/session-integrity"
import {
  getTechnicalCameraStream,
  getTechnicalMicrophoneStream,
  releaseTechnicalPermissions,
} from "@/lib/technical-permissions"
type SessionMode = "mock-ai" | "mock-voice"
type InterviewState = "connecting" | "ready" | "active" | "recovering" | "ending" | "analyzing" | "complete"
type JobContext = {
  role?: string | null
  company?: string | null
  job_title?: string | null
  jd_summary?: string | null
  key_skills?: string[]
  profile_type?: string | null
  profile_label?: string | null
}
interface TranscriptMessage {
  role: "interviewer" | "user"
  text: string
  isPartial?: boolean
  questionId?: string
}
type BrowserSpeechRecognitionResult = {
  isFinal: boolean
  0: { transcript: string }
}
type BrowserSpeechRecognitionResults = {
  length: number
  [index: number]: BrowserSpeechRecognitionResult
}
type BrowserSpeechRecognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: { resultIndex: number; results: BrowserSpeechRecognitionResults }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
  start: () => void
  stop: () => void
}
type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition

function getBrowserSpeechRecognition(): BrowserSpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null
  const browserWindow = window as Window & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor
  }
  return browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition || null
}
function buildInterviewWsUrl(apiBase: string, ticket: string) {
  const hostBase = /^https?:\/\//i.test(apiBase)
    ? apiBase.replace(/^http/i, "ws").replace(/\/api\/?$/, "")
    : window.location.origin.replace(/^http/i, "ws")
  return `${hostBase}/api/interview/ws/video/${ticket}`
}

function createEnvelopeId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID()
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16)
    return (char === "x" ? random : (random & 0x3) | 0x8).toString(16)
  })
}
export default function InterviewRoom() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const sessionId = params.id as string
  const requestedMode = searchParams.get("mode")
  const mode: SessionMode = "mock-voice"
  const inputMode: "voice" = "voice"
  const cameraEnabled = true
  const recoveryGraceSeconds = readRecoveryGraceSeconds()
  const sessionControlLock = useSessionControlLock(sessionId)
  const voiceMode = inputMode === "voice"
  const requiresStrictPermissions = true
  const [isMicOn, setIsMicOn] = useState(false)
  const [isVideoOn, setIsVideoOn] = useState(cameraEnabled)
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [hints, setHints] = useState<string[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [interviewState, setInterviewState] = useState<InterviewState>("connecting")
  const [currentQuestion, setCurrentQuestion] = useState("")
  const [currentTopic, setCurrentTopic] = useState("")
  const [progress, setProgress] = useState("")
  const [pipelineMode, setPipelineMode] = useState<"full" | "audio_only" | "legacy">("legacy")
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [aiSpeaking, setAiSpeaking] = useState(false)
  const [isCapturing, setIsCapturing] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionTimer, setSessionTimer] = useState(0)
  const [showAnalyzing, setShowAnalyzing] = useState(false)
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  const [interviewerName, setInterviewerName] = useState("Interviewer")
  const [interviewerTitle, setInterviewerTitle] = useState("Interview Round")
  const [jobContext, setJobContext] = useState<JobContext | null>(null)
  const [textAnswer, setTextAnswer] = useState("")
  const [textSubmitting, setTextSubmitting] = useState(false)
  const activeAudioRef = useRef<HTMLAudioElement[]>([])
  const audioQueueRef = useRef<Promise<void>>(Promise.resolve())
  const videoRef = useRef<HTMLVideoElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const clientSessionIdRef = useRef(createEnvelopeId())
  const clientSequenceRef = useRef(0)
  const localStreamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const sessionRecorderRef = useRef<MediaRecorder | null>(null)
  const recordedChunksRef = useRef<Blob[]>([])
  const sessionChunkIndexRef = useRef(0)
  const discardRecordingRef = useRef(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const aiTokenBufferRef = useRef("")
  const partialTranscriptRef = useRef("")
  const lastQuestionIdRef = useRef<string | null>(null)
  const lastFaceMetricSentRef = useRef(0)
  const pageLoadTimeRef = useRef(Date.now())
  const mediaCleanupDoneRef = useRef(false)
  const interviewEndSentRef = useRef(false)
  const interviewStartedRef = useRef(false)
  const interviewStateRef = useRef<InterviewState>("connecting")
  const recoveryStartedAtRef = useRef<number | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cameraLossTimerRef = useRef<number | null>(null)
  const questionStartedAtRef = useRef(Date.now())
  const speechRecordingStartedAtRef = useRef<number | null>(null)
  const speechQuestionIdRef = useRef<string | null>(null)
  const speechIdempotencyKeyRef = useRef<string | null>(null)
  const answerInFlightRef = useRef(false)
  const aiSpeakingRef = useRef(false)
  const isProcessingRef = useRef(false)
  const liveSubtitleRecognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const liveSubtitleQuestionIdRef = useRef<string | null>(null)
  const pendingTextAnswerRef = useRef<{ idempotencyKey: string; text: string } | null>(null)
  const cleanupInterviewEnvironmentRef = useRef<(options?: { complete?: boolean; keepalive?: boolean }) => void>(() => {})
  const deferredUnmountCleanupRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sendClientEvent = useCallback((
    type: string,
    payload: Record<string, unknown> = {},
    target: WebSocket | null = wsRef.current,
  ) => {
    if (!target || target.readyState !== WebSocket.OPEN) return null
    clientSequenceRef.current += 1
    const eventId = createEnvelopeId()
    target.send(JSON.stringify({
      event_id: eventId,
      sequence: clientSequenceRef.current,
      client_session_id: clientSessionIdRef.current,
      interview_id: sessionId,
      type,
      sent_at: new Date().toISOString(),
      payload,
    }))
    return eventId
  }, [sessionId])
  const getSupportedAudioMimeType = useCallback(() => {
    if (typeof MediaRecorder === "undefined") return ""
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ]
    return candidates.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || ""
  }, [])
  const blobToBase64 = useCallback((blob: Blob) => {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => {
        const result = reader.result
        if (typeof result !== "string") {
          reject(new Error("Failed to read audio blob"))
          return
        }
        resolve(result.split(",")[1] || "")
      }
      reader.onerror = () => reject(new Error("Failed to encode audio blob"))
      reader.readAsDataURL(blob)
    })
  }, [])
  const registerMediaChunk = useCallback(async (blob: Blob, mediaKind: "video" | "audio" = "video") => {
    try {
      const chunkIndex = sessionChunkIndexRef.current++
      const uploadResp = await fetch(`${API_CONFIG.BASE_URL}/interview/${sessionId}/media/upload-url`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          media_kind: mediaKind,
          content_type: blob.type || "video/webm",
          byte_size: blob.size,
          chunk_index: chunkIndex,
        }),
      })
      if (!uploadResp.ok) return
      const upload = await uploadResp.json()
      await fetch(`${API_CONFIG.BASE_URL}/interview/${sessionId}/media/chunk-complete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          asset_id: upload.asset_id,
          media_kind: mediaKind,
          object_key: upload.object_key,
          content_type: blob.type || "video/webm",
          byte_size: blob.size,
          chunk_index: chunkIndex,
          metadata: { browser_recorded: true },
        }),
      })
    } catch {
    }
  }, [sessionId])
  const startSessionRecording = useCallback((stream: MediaStream) => {
    if (typeof MediaRecorder === "undefined" || sessionRecorderRef.current) return
    const mediaKind = stream.getVideoTracks().length > 0 ? "video" : "audio"
    const candidates = mediaKind === "video"
      ? ["video/webm;codecs=vp8,opus", "video/webm"]
      : ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
    const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || ""
    try {
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) void registerMediaChunk(event.data, mediaKind)
      }
      recorder.start(10000)
      sessionRecorderRef.current = recorder
    } catch {
      sendClientEvent("anti_cheat_event", { event_type: "recording_failed", payload: {} })
    }
  }, [registerMediaChunk, sendClientEvent])
  const stopSessionRecording = useCallback(() => {
    const recorder = sessionRecorderRef.current
    if (recorder && recorder.state !== "inactive") recorder.stop()
    sessionRecorderRef.current = null
  }, [])
  const stopSpeechRecording = useCallback((discard = false) => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === "inactive") return
    discardRecordingRef.current = discard
    recorder.stop()
  }, [])
  const startSpeechRecording = useCallback(() => {
    if (typeof MediaRecorder === "undefined") return false
    const stream = localStreamRef.current
    if (!stream) return false

    const enabledAudioTracks = stream.getAudioTracks().filter((track) => track.enabled)
    if (enabledAudioTracks.length === 0) return false
    if (mediaRecorderRef.current?.state === "recording") return false

    const mimeType = getSupportedAudioMimeType()
    const recordingStream = new MediaStream(enabledAudioTracks)
    const recorder = mimeType
      ? new MediaRecorder(recordingStream, { mimeType })
      : new MediaRecorder(recordingStream)

    recordedChunksRef.current = []
    discardRecordingRef.current = false

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        recordedChunksRef.current.push(event.data)
      }
    }

    recorder.onstop = async () => {
      const chunks = recordedChunksRef.current
      const shouldDiscard = discardRecordingRef.current
      const socket = wsRef.current
      const blobType = recorder.mimeType || mimeType || "audio/webm"
      const durationMs = speechRecordingStartedAtRef.current
        ? Math.max(0, Date.now() - speechRecordingStartedAtRef.current)
        : 0

      mediaRecorderRef.current = null
      speechRecordingStartedAtRef.current = null
      const questionId = speechQuestionIdRef.current
      const idempotencyKey = speechIdempotencyKeyRef.current
      speechQuestionIdRef.current = null
      speechIdempotencyKeyRef.current = null
      recordedChunksRef.current = []
      discardRecordingRef.current = false

      if (shouldDiscard || chunks.length === 0) {
        answerInFlightRef.current = false
        setIsProcessing(false)
        return
      }

      if (!socket || socket.readyState !== WebSocket.OPEN) {
        answerInFlightRef.current = false
        setIsProcessing(false)
        return
      }

      try {
        const audioBlob = new Blob(chunks, { type: blobType })
        const audioBase64 = await blobToBase64(audioBlob)
        sendClientEvent("audio_chunk", {
          audio: audioBase64,
          mime_type: blobType,
          duration_ms: durationMs,
          question_id: questionId,
          idempotency_key: idempotencyKey,
          timing: {
            response_seconds: Math.max(0, (Date.now() - questionStartedAtRef.current) / 1000),
            voiced_duration_seconds: durationMs / 1000,
          },
        }, socket)
      } catch {
        answerInFlightRef.current = false
        setIsProcessing(false)
        toast.error("Failed to send audio. Please try again.")
      }
    }

    recorder.start()
    speechRecordingStartedAtRef.current = Date.now()
    speechQuestionIdRef.current = lastQuestionIdRef.current
    speechIdempotencyKeyRef.current = createEnvelopeId()
    mediaRecorderRef.current = recorder
    return true
  }, [blobToBase64, getSupportedAudioMimeType, sendClientEvent])
  const stopLiveSubtitleRecognition = useCallback(() => {
    const recognition = liveSubtitleRecognitionRef.current
    liveSubtitleRecognitionRef.current = null
    liveSubtitleQuestionIdRef.current = null
    if (!recognition) return
    recognition.onresult = null
    recognition.onend = null
    recognition.onerror = null
    try {
      recognition.stop()
    } catch {
    }
  }, [])
  const startLiveSubtitleRecognition = useCallback(() => {
    const Recognition = getBrowserSpeechRecognition()
    if (!Recognition || liveSubtitleRecognitionRef.current) return
    let recognition: BrowserSpeechRecognition
    try {
      recognition = new Recognition()
    } catch {
      return
    }
    recognition.lang = "en-US"
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    liveSubtitleQuestionIdRef.current = lastQuestionIdRef.current
    recognition.onresult = (event) => {
      const transcript = Array.from({ length: event.results.length }, (_, index) => {
        const result = event.results[index]
        return result?.[0]?.transcript || ""
      }).join(" ").replace(/\s+/g, " ").trim()
      if (!transcript) return
      const questionId = liveSubtitleQuestionIdRef.current || lastQuestionIdRef.current || undefined
      setMessages((prev) => [
        ...prev.filter((message) => !message.isPartial),
        { role: "user", text: transcript, isPartial: true, ...(questionId ? { questionId } : {}) },
      ])
    }
    recognition.onerror = () => {
      if (liveSubtitleRecognitionRef.current === recognition) {
        liveSubtitleRecognitionRef.current = null
      }
    }
    recognition.onend = () => {
      if (liveSubtitleRecognitionRef.current === recognition) {
        liveSubtitleRecognitionRef.current = null
      }
    }
    liveSubtitleRecognitionRef.current = recognition
    try {
      recognition.start()
    } catch {
      if (liveSubtitleRecognitionRef.current === recognition) {
        liveSubtitleRecognitionRef.current = null
      }
    }
  }, [])
  const {
    metrics: streamingMetrics,
    updateEngagement,
    updateCameraContact,
    addTranscriptWords,
    setDynamicTip,
    resetSpeechTracking,
  } = useStreamingMetrics()
  const { metrics: faceMetrics, start: startFaceCheck, stop: stopFaceCheck } = useFaceCheck(videoRef)
  useAudioEnvironment(localStream, {
    enabled: voiceMode && interviewState === "active",
    onBackgroundAudioDetected: useCallback((details: { type: string; confidence: number }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        sendClientEvent("anti_cheat_event", {
          event_type: "background_audio_detected",
          payload: details,
        })
      }
      toast.warning(
        details.type === "background_music"
          ? "Background music detected. Please mute other audio sources during the interview."
          : "Background audio detected. Please ensure a quiet environment for the interview."
      )
    }, [sendClientEvent]),
  })
  useEffect(() => {
    interviewStateRef.current = interviewState
  }, [interviewState])
  useEffect(() => {
    aiSpeakingRef.current = aiSpeaking
  }, [aiSpeaking])
  useEffect(() => {
    isProcessingRef.current = isProcessing
  }, [isProcessing])
  useEffect(() => {
    if (requestedMode && requestedMode !== "mock-voice") {
      toast.info("Opening your Interview Round.")
      router.replace(`/interview/${sessionId}?mode=mock-voice`)
    }
  }, [requestedMode, router, sessionId])
  const vad = useVAD({
    onSpeechStart: () => {
      if (
        interviewStateRef.current !== "active"
        || aiSpeakingRef.current
        || isProcessingRef.current
        || answerInFlightRef.current
      ) return
      if (!startSpeechRecording()) return
      setIsCapturing(true)
      setIsProcessing(false)
      startLiveSubtitleRecognition()
    },
    onSpeechEnd: (duration) => {
      if (answerInFlightRef.current || !mediaRecorderRef.current) return
      answerInFlightRef.current = true
      setIsCapturing(false)
      setIsProcessing(true)
      stopLiveSubtitleRecognition()
      stopSpeechRecording()
      updateEngagement(duration)
    },
    onVADMisfire: () => {
      setIsCapturing(false)
      setIsProcessing(false)
      stopLiveSubtitleRecognition()
      stopSpeechRecording(true)
    },
  })
  useEffect(() => {
    if (faceMetrics) {
      updateCameraContact(
        faceMetrics.engagementScore,
        faceMetrics.cameraContactLevel
      )
      const now = Date.now()
      if (
        interviewState === "active" &&
        wsRef.current?.readyState === WebSocket.OPEN &&
        now - lastFaceMetricSentRef.current > 1200
      ) {
        lastFaceMetricSentRef.current = now
        sendClientEvent("body_language_metrics", {
          metrics: faceMetrics,
        })
      }
    }
  }, [faceMetrics, interviewState, sendClientEvent, updateCameraContact])
  useEffect(() => {
    if (interviewState !== "active" || !localStream || !isVideoOn) return
    startFaceCheck()
    return () => stopFaceCheck()
  }, [interviewState, isVideoOn, localStream, startFaceCheck, stopFaceCheck])
  useEffect(() => {
    const videoTrack = localStream?.getVideoTracks()[0]
    if (!videoTrack) return
    const handleCameraEnded = () => {
      if (interviewEndSentRef.current || interviewStateRef.current !== "active") return
      setIsVideoOn(false)
      sendClientEvent("anti_cheat_event", {
        event_type: "camera_track_ended",
        payload: {},
      })
      toast.error("Camera connection was interrupted. Restore camera access to continue.")
      if (cameraLossTimerRef.current) window.clearTimeout(cameraLossTimerRef.current)
      cameraLossTimerRef.current = window.setTimeout(() => {
        const hasLiveCamera = Boolean(
          localStreamRef.current?.getVideoTracks().some((track) => track.readyState === "live" && track.enabled)
        )
        if (hasLiveCamera || interviewEndSentRef.current) return
        interviewEndSentRef.current = true
        void cancelInterviewSession(sessionId).finally(() => {
          cleanupInterviewEnvironmentRef.current()
          router.replace("/?tab=interview")
        })
      }, recoveryGraceSeconds * 1000)
    }
    videoTrack.addEventListener("ended", handleCameraEnded)
    return () => videoTrack.removeEventListener("ended", handleCameraEnded)
  }, [localStream, recoveryGraceSeconds, router, sendClientEvent, sessionId])
  useEffect(() => {
    async function setupMedia() {
      if (!voiceMode && !cameraEnabled) {
        setIsMicOn(false)
        setIsVideoOn(false)
        return
      }
      try {
        const preflightCamera = getTechnicalCameraStream()
        const preflightMicrophone = getTechnicalMicrophoneStream()
        const preflightTracks = [
          ...(preflightCamera?.getVideoTracks() || []),
          ...(voiceMode ? preflightMicrophone?.getAudioTracks() || [] : []),
        ].filter((track) => track.readyState === "live")
        const hasPreflightVideo = preflightTracks.some((track) => track.kind === "video")
        const hasPreflightAudio = !voiceMode || preflightTracks.some((track) => track.kind === "audio")
        const stream = hasPreflightVideo && hasPreflightAudio
          ? new MediaStream(preflightTracks)
          : await navigator.mediaDevices.getUserMedia({ video: true, audio: voiceMode })
        if (videoRef.current) videoRef.current.srcObject = stream
        localStreamRef.current = stream
        setLocalStream(stream)
        startSessionRecording(stream)
      } catch {
        toast.error(voiceMode
          ? "Camera and microphone access are required for the Interview Round. Allow both, then retry."
          : "Camera access is required for the Interview Round. Allow it, then retry.")
        setIsVideoOn(false)
        setIsMicOn(false)
      }
    }
    setupMedia()
    return () => {
      stopLiveSubtitleRecognition()
      stopSpeechRecording(true)
      stopSessionRecording()
      localStreamRef.current?.getTracks().forEach((t) => t.stop())
      localStreamRef.current = null
      setLocalStream(null)
      stopFaceCheck()
    }
  }, [cameraEnabled, startSessionRecording, stopFaceCheck, stopLiveSubtitleRecognition, stopSessionRecording, stopSpeechRecording, voiceMode])
  const handleWSMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        switch (data.type) {
          case "session_started":
            setInterviewState("ready")
            const restoredQuestionId = data.question_id || data.current_question_id || lastQuestionIdRef.current
            lastQuestionIdRef.current = restoredQuestionId
            questionStartedAtRef.current = Date.now()
            if (data.settings?.interview_activated_at) {
              const startedAt = Date.parse(data.settings.interview_activated_at)
              if (Number.isFinite(startedAt)) {
                setSessionTimer(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
              }
            } else {
              setSessionTimer(0)
            }
            if (data.audio_pending) setAiSpeaking(true)
            if (data.persona) {
              if (data.persona.name) setInterviewerName(data.persona.name)
              if (data.persona.role) setInterviewerTitle(data.persona.role)
            }
            if (data.settings?.job_context && typeof data.settings.job_context === "object") {
              setJobContext(data.settings.job_context as JobContext)
            }
            if (data.opening_text) {
              setCurrentQuestion(data.current_question || data.opening_text)
              setCurrentTopic(data.current_topic || "Warm-up")
              setProgress(data.progress || "Warm-up")
              setMessages((prev) => prev.some((item) => item.role === "interviewer" && item.questionId === restoredQuestionId)
                ? prev
                : [...prev, { role: "interviewer", text: data.opening_text, questionId: restoredQuestionId }])
            }
            if (data.opening_audio) {
              playAudioBase64(data.opening_audio)
            }
            break
          case "pipeline_ready":
            interviewStartedRef.current = true
            recoveryStartedAtRef.current = null
            reconnectAttemptRef.current = 0
            setPipelineMode(data.pipeline_mode)
            setIsProcessing(false)
            if (data.avatar_session?.sdp_offer) {
              setRemoteStream(new MediaStream())
            }
            setInterviewState("active")
            if (data.activated_at) {
              const activatedAt = Date.parse(data.activated_at)
              setSessionTimer(Number.isFinite(activatedAt)
                ? Math.max(0, Math.floor((Date.now() - activatedAt) / 1000))
                : 0)
            } else if (!interviewStartedRef.current) {
              setSessionTimer(0)
            }
            if (timerRef.current) clearInterval(timerRef.current)
            timerRef.current = setInterval(() => {
              setSessionTimer((prev) => prev + 1)
            }, 1000)
            break
          case "question":
            if (data.requires_ack && data.question_id && wsRef.current?.readyState === WebSocket.OPEN) {
              sendClientEvent("question_ack", {
                question_id: data.question_id,
                delivery_id: data.delivery_id,
                sequence: data.sequence,
              })
            }
            if (data.question_id && lastQuestionIdRef.current === data.question_id) {
              if (!answerInFlightRef.current) {
                setIsProcessing(false)
                setTextSubmitting(false)
              }
              break
            }
            answerInFlightRef.current = false
            lastQuestionIdRef.current = data.question_id || null
            questionStartedAtRef.current = Date.now()
            pendingTextAnswerRef.current = null
            setTextSubmitting(false)
            setTextAnswer("")
            setIsProcessing(false)
            setCurrentQuestion(data.question_text)
            setCurrentTopic(data.topic)
            setProgress(data.progress)
            setMessages((prev) => [
              ...prev,
              { role: "interviewer", text: data.question_text, questionId: data.question_id },
            ])
            if (data.audio_pending) setAiSpeaking(true)
            if (data.question_audio) {
              playAudioBase64(data.question_audio)
            }
            break
          case "transcription_partial":
            partialTranscriptRef.current = data.text
            setMessages((prev) => {
              const filtered = prev.filter((m) => !m.isPartial)
              return [...filtered, { role: "user", text: data.text, isPartial: true }]
            })
            break
          case "transcription_final":
            if (data.role === "user") {
              stopLiveSubtitleRecognition()
              partialTranscriptRef.current = ""
              setMessages((prev) => {
                const filtered = prev.filter((m) => !m.isPartial)
                if (pendingTextAnswerRef.current?.text.trim() === String(data.text || "").trim()) {
                  return filtered
                }
                return [...filtered, { role: "user", text: data.text, questionId: lastQuestionIdRef.current || undefined }]
              })
              addTranscriptWords(data.text)
              resetSpeechTracking()
            }
            break
          case "answer_committed":
            if (
              pendingTextAnswerRef.current
              && data.idempotency_key
              && data.idempotency_key !== pendingTextAnswerRef.current.idempotencyKey
            ) {
              break
            }
            pendingTextAnswerRef.current = null
            setTextSubmitting(false)
            setIsProcessing(true)
            if (data.duplicate) toast.info("That answer was already saved. Continuing from the saved response.")
            break
          case "ai_token":
            aiTokenBufferRef.current += data.token
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "interviewer" && last.isPartial) {
                return [
                  ...prev.slice(0, -1),
                  { role: "interviewer", text: aiTokenBufferRef.current, isPartial: true },
                ]
              }
              return [
                ...prev,
                { role: "interviewer", text: aiTokenBufferRef.current, isPartial: true },
              ]
            })
            break
          case "ai_response_complete":
            setMessages((prev) => {
              const filtered = prev.filter(
                (m) => !(m.role === "interviewer" && m.isPartial)
              )
              return [...filtered, { role: "interviewer", text: data.text }]
            })
            aiTokenBufferRef.current = ""
            setAiSpeaking(true)
            if (!answerInFlightRef.current) setIsProcessing(false)
            break
          case "ai_interrupted":
            setAiSpeaking(false)
            aiTokenBufferRef.current = ""
            break
          case "audio_chunk":
            void playAudioBase64(data.audio, data.audio_mime_type || "audio/wav")
            setAiSpeaking(true)
            break
          case "speech_unavailable":
            answerInFlightRef.current = false
            stopLiveSubtitleRecognition()
            setAiSpeaking(false)
            setIsProcessing(false)
            if (data.message) toast.info(data.message)
            break
          case "answer_quality_feedback":
            if (data.message) {
              setMessages((prev) => [
                ...prev,
                { role: "interviewer", text: data.message },
              ])
              if (data.severity === "error") toast.error(data.message)
              else toast.warning(data.message)
            }
            break
          case "answer_rejected":
            answerInFlightRef.current = false
            stopLiveSubtitleRecognition()
            setIsProcessing(false)
            if (data.message && !data.quality_failure_streak) toast.info(data.message)
            break
          case "evaluation":
            setIsProcessing(false)
            updateEngagement(2000, data.score / 100)
            break
          case "dynamic_tooltip":
            setDynamicTip(data.tip)
            setHints((prev) => [...prev.slice(-4), data.tip])
            break
          case "vad_state":
            setIsCapturing(data.speaking)
            setIsProcessing(data.processing || false)
            break
          case "body_language":
            const contactVal = data.eye_contact ? 80 : 40
            updateCameraContact(contactVal, data.eye_contact ? "Optimal" : "Low")
            break
          case "interview_ending":
            cleanupInterviewEnvironmentRef.current()
            setInterviewState("analyzing")
            setShowAnalyzing(true)
            break
          case "interview_complete":
            setIsProcessing(false)
            if (data.closing_text) {
              setMessages((prev) => [
                ...prev,
                { role: "interviewer", text: data.closing_text },
              ])
            }
            void (async () => {
              if (data.closing_audio) {
                await playAudioBase64(data.closing_audio, data.audio_mime_type || "audio/wav")
              }
              cleanupInterviewEnvironmentRef.current()
              setInterviewState("analyzing")
              setShowAnalyzing(true)
            })()
            break
          case "interview_already_finalized":
            setIsProcessing(false)
            setInterviewState("complete")
            cleanupInterviewEnvironmentRef.current()
            router.replace(data.redirect_to || `/interview/${sessionId}/report`)
            break
          case "error":
            answerInFlightRef.current = false
            stopLiveSubtitleRecognition()
            setIsProcessing(false)
            setTextSubmitting(false)
            pendingTextAnswerRef.current = null
            toast.error(data.message)
            break
        }
      } catch {
        toast.error("Received an invalid interview message.")
      }
    },
    [mode, router, sessionId, addTranscriptWords, resetSpeechTracking, sendClientEvent, stopLiveSubtitleRecognition, updateEngagement, updateCameraContact, setDynamicTip]
  )
  useEffect(() => {
    if (sessionControlLock !== "owned") return
    let cancelled = false

    const endExpiredRecovery = async () => {
      if (cancelled || interviewEndSentRef.current) return
      interviewEndSentRef.current = true
      setInterviewState("ending")
      try {
        await cancelInterviewSession(sessionId)
      } catch {
        // The durable backend recovery sweeper remains authoritative if this
        // final client request cannot be delivered.
      } finally {
        cleanupInterviewEnvironmentRef.current({ complete: true })
        toast.error("The connection recovery window expired. This attempt was marked incomplete.")
        router.replace("/?tab=interview")
      }
    }

    const scheduleReconnect = () => {
      if (cancelled || interviewEndSentRef.current) return
      const recoveryStartedAt = recoveryStartedAtRef.current ?? Date.now()
      recoveryStartedAtRef.current = recoveryStartedAt
      const elapsed = Date.now() - recoveryStartedAt
      const graceMs = recoveryGraceSeconds * 1000
      if (elapsed >= graceMs) {
        void endExpiredRecovery()
        return
      }
      setInterviewState("recovering")
      const delay = Math.min(4000, 500 * (2 ** reconnectAttemptRef.current))
      reconnectAttemptRef.current += 1
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null
        void connectWebSocket()
      }, Math.min(delay, graceMs - elapsed))
    }

    async function connectWebSocket() {
      const apiBase = API_CONFIG.BASE_URL
      try {
        const ticketRes = await fetch(`${apiBase}/interview/ws-ticket`, {
          method: "POST",
          credentials: "include",
          headers: getAuthHeaders(),
        })
        if (!ticketRes.ok) {
          const body = await ticketRes.json().catch(() => null)
          if (ticketRes.status === 401 || ticketRes.status === 403) {
            toast.error(body?.detail || body?.message || "Your session expired. Sign in again.")
            router.replace("/")
            return
          }
          scheduleReconnect()
          return
        }
        const { ticket } = await ticketRes.json()
        if (cancelled || !ticket) return

        const ws = new WebSocket(buildInterviewWsUrl(apiBase, ticket))

        ws.onopen = () => {
          setIsConnected(true)
          sendClientEvent("start_session", { interview_id: sessionId }, ws)
        }
        ws.onmessage = handleWSMessage
        ws.onclose = (event) => {
          setIsConnected(false)
          if (timerRef.current) clearInterval(timerRef.current)
          if (cancelled || interviewEndSentRef.current || mediaCleanupDoneRef.current) return
          if (event.code === 4010) {
            toast.error("This attempt is already active in another tab.")
            cleanupInterviewEnvironmentRef.current()
            router.replace("/?tab=interview")
            return
          }
          if (recoveryStartedAtRef.current === null) {
            toast.warning(`Connection interrupted. Reconnecting for up to ${recoveryGraceSeconds} seconds…`)
          }
          scheduleReconnect()
        }
        ws.onerror = () => {
          setIsConnected(false)
        }
        wsRef.current = ws
      } catch {
        scheduleReconnect()
      }
    }

    connectWebSocket()
    return () => {
      cancelled = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [handleWSMessage, recoveryGraceSeconds, router, sendClientEvent, sessionControlLock, sessionId])
  useEffect(() => {
    if (!voiceMode || interviewState !== "active" || !isMicOn || !localStreamRef.current) return
    const audioStream = new MediaStream(localStreamRef.current.getAudioTracks())
    if (audioStream.getAudioTracks().length === 0) return
    vad.startListening(audioStream)
    return () => {
      stopLiveSubtitleRecognition()
      stopSpeechRecording(true)
      vad.stopListening()
    }
  }, [aiSpeaking, interviewState, isMicOn, stopLiveSubtitleRecognition, stopSpeechRecording, voiceMode])
  useEffect(() => {
    if (!requiresStrictPermissions) return
    const lastPermissionDialogRef = { current: 0 }
    const sendAntiCheat = (eventType: string, payload: Record<string, unknown> = {}) => {
      sendClientEvent("anti_cheat_event", { event_type: eventType, payload })
    }
    const warnStrictMode = (eventType: string, message: string, payload: Record<string, unknown> = {}) => {
      sendAntiCheat(eventType, payload)
      toast.warning(message)
    }
    const onVisibility = () => {
      if (Date.now() - pageLoadTimeRef.current < 15000) return
      if (Date.now() - lastPermissionDialogRef.current < 3000) return
      if (document.visibilityState === "hidden") {
        warnStrictMode("tab_switch", "Strict mock warning: tab switching is flagged.", { visibilityState: document.visibilityState })
      }
    }
    const onBlur = () => {
      if (Date.now() - pageLoadTimeRef.current < 15000) return
      if (Date.now() - lastPermissionDialogRef.current < 3000) return
      warnStrictMode("window_blur", "Strict mock warning: leaving the interview window is logged.")
    }
    const onFullscreen = () => {
      if (Date.now() - pageLoadTimeRef.current < 15000) return
      lastPermissionDialogRef.current = Date.now()
      if (!document.fullscreenElement && interviewState === "active") {
        warnStrictMode("fullscreen_exit", "Strict mock warning: fullscreen exit is flagged.")
      }
    }
    const onPaste = (event: ClipboardEvent) => {
      event.preventDefault()
      warnStrictMode("paste_blocked", "Paste is disabled and this interview was flagged.")
    }
    document.addEventListener("visibilitychange", onVisibility)
    document.addEventListener("fullscreenchange", onFullscreen)
    window.addEventListener("blur", onBlur)
    document.addEventListener("paste", onPaste)
    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      document.removeEventListener("fullscreenchange", onFullscreen)
      window.removeEventListener("blur", onBlur)
      document.removeEventListener("paste", onPaste)
    }
  }, [requiresStrictPermissions, interviewState, sendClientEvent])
  const playAudioBase64 = useCallback((base64: string, mimeType = "audio/wav") => {
    audioQueueRef.current = audioQueueRef.current.then(() => new Promise<void>((resolve) => {
      try {
        const binary = atob(base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const blob = new Blob([bytes], { type: mimeType })
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        activeAudioRef.current.push(audio)
        setAiSpeaking(true)
        audio.onended = () => {
          URL.revokeObjectURL(url)
          activeAudioRef.current = activeAudioRef.current.filter(a => a !== audio)
          if (activeAudioRef.current.length === 0) {
            setAiSpeaking(false)
          }
          resolve()
        }
        audio.onerror = () => {
          URL.revokeObjectURL(url)
          activeAudioRef.current = activeAudioRef.current.filter(a => a !== audio)
          if (activeAudioRef.current.length === 0) {
            setAiSpeaking(false)
          }
          resolve()
        }
        audio.play().catch(() => {
          URL.revokeObjectURL(url)
          activeAudioRef.current = activeAudioRef.current.filter(a => a !== audio)
          setAiSpeaking(activeAudioRef.current.length > 0)
          resolve()
        })
      } catch {
        resolve()
      }
    }))
    return audioQueueRef.current
  }, [])
  const stopAllAudio = useCallback(() => {
    activeAudioRef.current.forEach(audio => {
      audio.pause()
      audio.currentTime = 0
      if (audio.src) URL.revokeObjectURL(audio.src)
    })
    activeAudioRef.current = []
    audioQueueRef.current = Promise.resolve()
    setAiSpeaking(false)
  }, [])
  const sendInterviewEnd = useCallback((keepalive = false) => {
    if (interviewEndSentRef.current) return
    interviewEndSentRef.current = true
    try {
      sendClientEvent("end_interview")
    } catch {
    }
    void endInterviewSession(sessionId, { keepalive }).catch(() => null)
  }, [sendClientEvent, sessionId])
  const cleanupInterviewEnvironment = useCallback((options: { complete?: boolean; keepalive?: boolean } = {}) => {
    if (options.complete) {
      sendInterviewEnd(Boolean(options.keepalive))
    }
    if (mediaCleanupDoneRef.current) return
    mediaCleanupDoneRef.current = true
    stopAllAudio()
    stopSpeechRecording(true)
    stopSessionRecording()
    vad.stopListening()
    stopFaceCheck()
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (cameraLossTimerRef.current) {
      clearTimeout(cameraLossTimerRef.current)
      cameraLossTimerRef.current = null
    }
    localStreamRef.current?.getTracks().forEach((track) => track.stop())
    localStreamRef.current = null
    setLocalStream(null)
    if (videoRef.current) videoRef.current.srcObject = null
    void releaseTechnicalPermissions()
  }, [sendInterviewEnd, stopAllAudio, stopFaceCheck, stopSessionRecording, stopSpeechRecording, vad])
  useEffect(() => {
    cleanupInterviewEnvironmentRef.current = cleanupInterviewEnvironment
  }, [cleanupInterviewEnvironment])
  const initPipeline = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      if (voiceMode && !localStreamRef.current?.getAudioTracks().length) {
        toast.error("Microphone access is required for the Interview Round. Allow microphone access, then retry.")
        return
      }
      if (!localStreamRef.current?.getVideoTracks().length) {
        toast.error("Camera access is required for the Interview Round. Allow camera access, then retry.")
        return
      }
      interviewStartedRef.current = true
      if (requiresStrictPermissions && document.fullscreenEnabled && !document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {
          sendClientEvent("anti_cheat_event", {
            event_type: "fullscreen_request_failed",
            payload: {},
          })
        })
      }
      sendClientEvent("init_pipeline", {
        input_mode: inputMode,
        camera_enabled: cameraEnabled,
      })
      setIsMicOn(voiceMode)
    }
  }, [cameraEnabled, inputMode, requiresStrictPermissions, sendClientEvent, voiceMode])
  useEffect(() => {
    if (interviewState !== "ready" || !isConnected) return
    if (voiceMode && !localStream?.getAudioTracks().length) return
    initPipeline()
  }, [initPipeline, interviewState, isConnected, localStream, voiceMode])
  const toggleMic = useCallback(() => {
    setIsMicOn((prev) => {
      const next = !prev
      localStreamRef.current?.getAudioTracks().forEach((t) => { t.enabled = next })
      if (!next) {
        stopSpeechRecording(true)
        setIsCapturing(false)
        setIsProcessing(false)
      }
      return next
    })
  }, [stopSpeechRecording])
  const toggleVideo = useCallback(() => {
    toast.info("Camera must remain on throughout the Interview Round.")
  }, [])
  const submitTextAnswer = useCallback(() => {
    const text = textAnswer.trim()
    if (!text || textSubmitting || isProcessing) return
    const socket = wsRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      toast.error("The interview connection is not ready. Your answer was not sent.")
      return
    }
    const questionId = lastQuestionIdRef.current
    const idempotencyKey = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `answer-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const responseSeconds = Math.max(0, Math.round((Date.now() - questionStartedAtRef.current) / 1000))
    pendingTextAnswerRef.current = { idempotencyKey, text }
    setTextSubmitting(true)
    setIsProcessing(true)
    setMessages((prev) => [...prev.filter((message) => !message.isPartial), { role: "user", text, ...(questionId ? { questionId } : {}) }])
    sendClientEvent("text_answer", {
      text,
      question_id: questionId,
      idempotency_key: idempotencyKey,
      response_seconds: responseSeconds,
      timing: { response_seconds: responseSeconds },
    }, socket)
  }, [isProcessing, sendClientEvent, textAnswer, textSubmitting])
  const requestEndCall = useCallback(() => {
    setShowEndConfirm(true)
  }, [])
  const confirmEndCall = useCallback(async () => {
    setShowEndConfirm(false)
    setInterviewState("ending")
    cleanupInterviewEnvironment()
    try {
      await cancelInterviewSession(sessionId)
      router.replace("/?tab=interview")
    } catch (error) {
      interviewEndSentRef.current = false
      mediaCleanupDoneRef.current = false
      setInterviewState("active")
      toast.error(error instanceof Error ? error.message : "Could not end this attempt. Check your connection and try again.")
    }
  }, [cleanupInterviewEnvironment, router, sessionId])
  const cancelEndCall = useCallback(() => {
    setShowEndConfirm(false)
  }, [])

  useEffect(() => {
    if (showAnalyzing || interviewState === "complete") return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    const onPageHide = () => {
      if (!interviewEndSentRef.current) {
        interviewEndSentRef.current = true
        void abandonInterviewSession(sessionId, { keepalive: true }).catch(() => undefined)
      }
      cleanupInterviewEnvironment()
    }
    window.addEventListener("beforeunload", onBeforeUnload)
    window.addEventListener("pagehide", onPageHide)
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload)
      window.removeEventListener("pagehide", onPageHide)
    }
  }, [cleanupInterviewEnvironment, interviewState, sessionId, showAnalyzing])

  useEffect(() => {
    if (showAnalyzing || interviewState === "complete") return
    window.history.pushState({ interviewGuard: true }, "", window.location.href)
    const onPopState = () => {
      setShowEndConfirm(true)
      window.history.pushState({ interviewGuard: true }, "", window.location.href)
    }
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [interviewState, showAnalyzing])

  useEffect(() => {
    if (deferredUnmountCleanupRef.current) {
      clearTimeout(deferredUnmountCleanupRef.current)
      deferredUnmountCleanupRef.current = null
    }
    return () => {
      // React development mode replays mount effects once. Defer cleanup by
      // one task so the replay can cancel it instead of stopping the media
      // streams acquired by the dashboard preflight immediately after route
      // entry. A real unmount still runs the cleanup on the next task.
      deferredUnmountCleanupRef.current = setTimeout(() => {
        deferredUnmountCleanupRef.current = null
        cleanupInterviewEnvironmentRef.current()
      }, 0)
    }
  }, [])

  const formatTimer = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, "0")
    const s = (seconds % 60).toString().padStart(2, "0")
    return `${m}:${s}`
  }
  const layoutProps = {
    isMicOn,
    isVideoOn,
    videoRef,
    onToggleMic: toggleMic,
    onToggleVideo: toggleVideo,
    onEndCall: requestEndCall,
    showEndConfirm,
    onConfirmEnd: confirmEndCall,
    onCancelEnd: cancelEndCall,
    messages,
    hints,
    currentQuestion,
    currentTopic,
    progress,
    isConnected,
    interviewState,
    pipelineMode,
    remoteStream,
    aiSpeaking,
    isCapturing,
    isProcessing,
    sessionTimer,
    streamingMetrics,
    formatTimer,
    initPipeline,
    localStream,
    showQuestionText: true,
    interviewerName,
    interviewerTitle,
    jobContext,
    inputMode,
    cameraEnabled,
    textAnswer,
    textSubmitting,
    onTextAnswerChange: setTextAnswer,
    onSubmitTextAnswer: submitTextAnswer,
  }
  if (showAnalyzing || interviewState === "analyzing") {
    return (
      <AnalyzingOverlay
        isVisible
        interviewId={sessionId}
        onComplete={() => router.replace(`/interview/${sessionId}/report`)}
      />
    )
  }

  if (sessionControlLock === "blocked") {
    return <DuplicateSessionScreen onBack={() => router.replace("/?tab=interview")} />
  }

  if (sessionControlLock !== "owned") {
    return <MeetConnectingOverlay state="connecting" />
  }

  return <MockVoiceLayout {...layoutProps} />
}
interface LayoutProps {
  isMicOn: boolean
  isVideoOn: boolean
  videoRef: React.RefObject<HTMLVideoElement | null>
  onToggleMic: () => void
  onToggleVideo: () => void
  onEndCall: () => void
  showEndConfirm: boolean
  onConfirmEnd: () => void
  onCancelEnd: () => void
  messages: TranscriptMessage[]
  hints: string[]
  currentQuestion: string
  currentTopic: string
  progress: string
  isConnected: boolean
  interviewState: InterviewState
  pipelineMode: string
  remoteStream: MediaStream | null
  aiSpeaking: boolean
  isCapturing: boolean
  isProcessing: boolean
  sessionTimer: number
  streamingMetrics: {
    engagement: { value: number; label: string }
    cameraContact: { value: number; label: string }
    pace: { wpm: number; label: string }
    dynamicTip: string | null
  }
  formatTimer: (s: number) => string
  initPipeline: () => void
  localStream: MediaStream | null
  showQuestionText: boolean
  interviewerName?: string
  interviewerTitle?: string
  jobContext?: JobContext | null
  inputMode: "voice" | "text"
  cameraEnabled: boolean
  textAnswer: string
  textSubmitting: boolean
  onTextAnswerChange: (value: string) => void
  onSubmitTextAnswer: () => void
}
interface TranscriptMessage {
  role: "interviewer" | "user"
  text: string
  isPartial?: boolean
}
function EndConfirmDialog({ show, onConfirm, onCancel }: { show: boolean; onConfirm: () => void; onCancel: () => void }) {
  if (!show) return null
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-sm mx-4 rounded-2xl bg-card border border-border shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="p-6 text-center">
          <div className="w-14 h-14 rounded-full bg-destructive/15 flex items-center justify-center mx-auto mb-4">
            <AlertTriangle className="w-7 h-7 text-destructive" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">End this attempt?</h3>
          <p className="text-sm text-muted-foreground leading-relaxed">
            This session cannot be resumed. Available evidence will be kept, but the attempt will be marked incomplete and will not receive an official final score.
          </p>
        </div>
        <div className="flex border-t border-border">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-3.5 text-sm font-medium text-primary hover:bg-border/50 transition-colors"
          >
            Stay in session
          </button>
          <div className="w-px bg-border" />
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-3.5 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
          >
            End attempt
          </button>
        </div>
      </div>
    </div>
  )
}

function DuplicateSessionScreen({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-7 text-center shadow-xl">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-500/15">
          <AlertTriangle className="h-7 w-7 text-amber-600 dark:text-amber-300" />
        </div>
        <h1 className="text-xl font-semibold">Attempt already open</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          This continuous attempt is controlled by another tab. Return to that tab, or close it before reopening this session.
        </p>
        <button onClick={onBack} className="mt-6 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground">
          Back
        </button>
      </div>
    </div>
  )
}

function MeetConnectingOverlay({ state }: { state: string }) {
  return (
    <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background">
      <div className="w-12 h-12 rounded-full border-[3px] border-border border-t-primary animate-spin mb-6" />
      <p className="text-muted-foreground text-sm">
        {state === "connecting" ? "Connecting…" : "Preparing question…"}
      </p>
    </div>
  )
}

function MeetCaptions({ show, lastUserMsg, isCapturing }: { show: boolean; lastUserMsg?: TranscriptMessage; isCapturing: boolean }) {
  if (!show || !lastUserMsg) return null
  return (
    <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-30 w-full max-w-2xl px-4">
      <div className="bg-background/95 backdrop-blur-md rounded-lg px-5 py-3 text-center shadow-xl">
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">You said</p>
        <p className="text-sm text-foreground leading-relaxed">
          {lastUserMsg.isPartial ? (
            <>
              <span className="text-muted-foreground">{lastUserMsg.text.slice(0, Math.floor(lastUserMsg.text.length * 0.4))}</span>
              <span className="text-foreground font-medium">{lastUserMsg.text.slice(Math.floor(lastUserMsg.text.length * 0.4))}</span>
            </>
          ) : (
            <span className="text-muted-foreground">{lastUserMsg.text}</span>
          )}
          {isCapturing && <span className="inline-block w-[2px] h-[14px] bg-primary ml-1 align-middle animate-pulse" />}
        </p>
      </div>
    </div>
  )
}

function MeetSelfTile({
  stream,
  videoRef,
  isVideoOn,
  isMicOn,
  compact = false,
}: {
  stream: MediaStream | null
  videoRef: React.RefObject<HTMLVideoElement | null>
  isVideoOn: boolean
  isMicOn: boolean
  compact?: boolean
}) {
  useEffect(() => {
    if (videoRef.current && stream && videoRef.current.srcObject !== stream) {
      videoRef.current.srcObject = stream
      void videoRef.current.play().catch(() => {})
    }
  }, [stream, videoRef, isVideoOn])

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg bg-secondary">
      {isVideoOn ? (
        <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover scale-x-[-1]" />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={`${compact ? "h-12 w-12 text-lg" : "h-24 w-24 text-3xl"} rounded-full bg-muted-foreground flex items-center justify-center font-medium text-primary-foreground`}>Y</div>
        </div>
      )}
      <div className="absolute bottom-3 left-3 z-10">
        <span className="text-foreground text-xs font-medium bg-background/70 backdrop-blur-sm px-2.5 py-1 rounded">You</span>
      </div>
      {!isMicOn && (
        <div className="absolute bottom-3 right-3 z-10">
          <div className="w-7 h-7 rounded-full bg-destructive flex items-center justify-center"><MicOff className="w-3.5 h-3.5 text-primary-foreground" /></div>
        </div>
      )}
    </div>
  )
}

function MockVoiceLayout(props: LayoutProps) {
  const [showCaptions, setShowCaptions] = useState(true)
  const lastUserMsg = [...props.messages].reverse().find(m => m.role === "user")
  return (
    <div className="relative flex h-screen flex-col overflow-hidden bg-secondary/20 text-foreground">
      {(props.interviewState === "connecting") && <MeetConnectingOverlay state={props.interviewState} />}
      {(props.interviewState === "ready" || props.interviewState === "recovering") && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background">
          <div className="w-24 h-24 rounded-full bg-primary flex items-center justify-center text-3xl font-medium text-primary-foreground shadow-sm mb-6">
            {props.interviewerName ? props.interviewerName.charAt(0) : "A"}
          </div>
          <p className="text-foreground text-lg font-medium">{props.interviewState === "recovering" ? "Restoring…" : "Starting…"}</p>
        </div>
      )}
      <div className="min-h-0 flex-1 p-3 sm:p-4">
        <CleanInterviewStage props={props} />
      </div>
      <MeetCaptions show={showCaptions} lastUserMsg={lastUserMsg} isCapturing={props.isCapturing} />
      <div className="z-30 grid min-h-20 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-t border-border bg-background px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm font-mono tabular-nums text-foreground">{props.formatTimer(props.sessionTimer)}</span>
          <span className="hidden text-xs text-muted-foreground sm:inline">Interview in progress</span>
        </div>
        <InterviewControls variant="meet" isMicOn={props.isMicOn} isVideoOn={props.isVideoOn} onToggleMic={props.onToggleMic} onToggleVideo={props.onToggleVideo} onEndCall={props.onEndCall} captionsEnabled={showCaptions} onToggleCaptions={() => setShowCaptions(!showCaptions)} endLabel="Leave interview" cameraLocked />
        <div className="hidden justify-self-end text-xs text-muted-foreground sm:block">Camera remains on</div>
      </div>
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}

function CleanInterviewStage({ props }: { props: LayoutProps }) {
  const status = props.isProcessing
    ? "Preparing the next question"
    : props.isCapturing
      ? "Listening"
      : props.aiSpeaking
        ? "Interviewer speaking"
        : "Ready for your answer"
  return (
    <div className="grid h-full min-h-[420px] gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
      <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
              {props.interviewerName?.charAt(0) || "A"}
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">{props.interviewerName || "AI Interviewer"}</p>
              <p className="text-xs text-muted-foreground">{props.interviewerTitle || "Interviewer"}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground">
            <span className={`h-2 w-2 rounded-full ${props.isConnected ? "bg-emerald-500" : "bg-amber-500"}`} />
            {props.isConnected ? "Live" : "Connecting"}
          </div>
        </header>
        {props.jobContext && (
          <details className="border-b border-border px-5 py-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium text-foreground">
              {props.jobContext.job_title || props.jobContext.role || "Role context"} · {props.jobContext.profile_label || "Interview"}
            </summary>
            {props.jobContext.jd_summary && <p className="mt-2 max-w-4xl leading-5">{props.jobContext.jd_summary}</p>}
            {!!props.jobContext.key_skills?.length && <p className="mt-1">Focus: {props.jobContext.key_skills.join(" · ")}</p>}
          </details>
        )}
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-10 text-center sm:px-12">
          {props.currentTopic && <p className="text-xs font-medium text-muted-foreground">{props.currentTopic}</p>}
          <h1 className="mt-3 max-w-3xl text-balance text-2xl font-semibold leading-relaxed text-foreground sm:text-3xl">
            {props.currentQuestion || "Your interview will begin in a moment."}
          </h1>
          <div className="mt-8 flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-sm text-muted-foreground">
            <span className={`h-2 w-2 rounded-full ${props.isCapturing || props.aiSpeaking ? "animate-pulse bg-primary" : "bg-muted-foreground/50"}`} />
            {status}
          </div>
        </div>
      </section>
      <aside className="flex min-h-0 flex-col gap-3">
        <div className="h-40 overflow-hidden rounded-xl border border-border bg-card shadow-sm lg:h-44">
          <MeetSelfTile stream={props.localStream} videoRef={props.videoRef} isVideoOn={props.isVideoOn} isMicOn={props.isMicOn} compact />
        </div>
        <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
          <div className="space-y-2 text-sm text-foreground">
            <p className="flex items-center justify-between"><span className="text-muted-foreground">Camera</span><span className="text-emerald-600 dark:text-emerald-300">On</span></p>
            <p className="flex items-center justify-between"><span className="text-muted-foreground">Microphone</span><span>{props.isMicOn ? "On" : "Muted"}</span></p>
          </div>
        </div>
      </aside>
    </div>
  )
}
