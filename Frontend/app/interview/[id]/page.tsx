"use client"
import { useState, useEffect, useRef, useCallback } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { ArrowLeft, Brain, Eye, Clock, MicOff, X, AlertTriangle } from "lucide-react"
import { InterviewHeader } from "@/components/interview/interview-header"
import { InterviewControls } from "@/components/interview/interview-controls"
import { WaveformVisualizer } from "@/components/interview/waveform-visualizer"
import { LiveTranscription } from "@/components/interview/live-transcription"
import { PerformanceMetrics } from "@/components/interview/performance-metrics"
import { SelfView } from "@/components/interview/self-view"
import { HintPanel } from "@/components/interview/hint-panel"
import { AvatarView } from "@/components/interview/avatar-view"
import { AnalyzingOverlay } from "@/components/interview/analyzing-overlay"
import { useVAD } from "@/hooks/use-vad"
import { useFaceCheck } from "@/hooks/use-face-check"
import { useStreamingMetrics } from "@/hooks/use-streaming-metrics"
import { API_CONFIG } from "@/lib/config"
type SessionMode = "practice-ai" | "practice-voice" | "mock-ai" | "mock-voice"
type InterviewState = "connecting" | "ready" | "active" | "ending" | "analyzing" | "complete"
interface TranscriptMessage {
  role: "interviewer" | "user"
  text: string
  isPartial?: boolean
}
export default function InterviewRoom() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const sessionId = params.id as string
  const mode = (searchParams.get("mode") as SessionMode) || "practice-ai"
  const [isMicOn, setIsMicOn] = useState(false)
  const [isVideoOn, setIsVideoOn] = useState(true)
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [hints, setHints] = useState<string[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [interviewState, setInterviewState] = useState<InterviewState>("connecting")
  const [isMobile, setIsMobile] = useState(false)
  const [currentQuestion, setCurrentQuestion] = useState("")
  const [currentTopic, setCurrentTopic] = useState("")
  const [progress, setProgress] = useState("")
  const [pipelineMode, setPipelineMode] = useState<"full" | "audio_only" | "legacy">("legacy")
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [aiSpeaking, setAiSpeaking] = useState(false)
  const [isCapturing, setIsCapturing] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionTimer, setSessionTimer] = useState(0)
  const [showAnalyzing, setShowAnalyzing] = useState(false)
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  const activeAudioRef = useRef<HTMLAudioElement[]>([])
  const audioQueueRef = useRef<Promise<void>>(Promise.resolve())
  const videoRef = useRef<HTMLVideoElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recordedChunksRef = useRef<Blob[]>([])
  const discardRecordingRef = useRef(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const aiTokenBufferRef = useRef("")
  const partialTranscriptRef = useRef("")
  const lastFaceMetricSentRef = useRef(0)
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
  const stopSpeechRecording = useCallback((discard = false) => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === "inactive") return
    discardRecordingRef.current = discard
    recorder.stop()
  }, [])
  const startSpeechRecording = useCallback(() => {
    if (typeof MediaRecorder === "undefined") return
    const stream = localStreamRef.current
    if (!stream) return

    const enabledAudioTracks = stream.getAudioTracks().filter((track) => track.enabled)
    if (enabledAudioTracks.length === 0) return
    if (mediaRecorderRef.current?.state === "recording") return

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

      mediaRecorderRef.current = null
      recordedChunksRef.current = []
      discardRecordingRef.current = false

      if (shouldDiscard || chunks.length === 0) {
        setIsProcessing(false)
        return
      }

      if (!socket || socket.readyState !== WebSocket.OPEN) {
        setIsProcessing(false)
        return
      }

      try {
        const audioBlob = new Blob(chunks, { type: blobType })
        const audioBase64 = await blobToBase64(audioBlob)
        socket.send(JSON.stringify({ type: "audio_chunk", audio: audioBase64 }))
      } catch {
        setIsProcessing(false)
        toast.error("Failed to send audio. Please try again.")
      }
    }

    recorder.start()
    mediaRecorderRef.current = recorder
  }, [blobToBase64, getSupportedAudioMimeType])
  const {
    metrics: streamingMetrics,
    updateEngagement,
    updateCameraContact,
    addTranscriptWords,
    setDynamicTip,
    resetSpeechTracking,
  } = useStreamingMetrics()
  const { metrics: faceMetrics, start: startFaceCheck, stop: stopFaceCheck } = useFaceCheck(videoRef)
  const vad = useVAD({
    onSpeechStart: () => {
      setIsCapturing(true)
      setIsProcessing(false)
      if (aiSpeaking) {
        setAiSpeaking(false)
      }
      startSpeechRecording()
    },
    onSpeechEnd: (duration) => {
      setIsCapturing(false)
      setIsProcessing(true)
      stopSpeechRecording()
      updateEngagement(duration)
    },
    onVADMisfire: () => {
      setIsCapturing(false)
      setIsProcessing(false)
      stopSpeechRecording(true)
    },
  })
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener("resize", check)
    return () => window.removeEventListener("resize", check)
  }, [])
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
        wsRef.current.send(JSON.stringify({
          type: "body_language_metrics",
          metrics: faceMetrics,
        }))
      }
    }
  }, [faceMetrics, interviewState, updateCameraContact])
  useEffect(() => {
    async function setupMedia() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        if (videoRef.current) videoRef.current.srcObject = stream
        localStreamRef.current = stream
        startFaceCheck()
      } catch {
        toast.error("Could not access camera or microphone.")
        setIsVideoOn(false)
        setIsMicOn(false)
      }
    }
    setupMedia()
    return () => {
      stopSpeechRecording(true)
      localStreamRef.current?.getTracks().forEach((t) => t.stop())
      stopFaceCheck()
    }
  }, [stopFaceCheck, stopSpeechRecording])
  const handleWSMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        switch (data.type) {
          case "session_started":
            setInterviewState("ready")
            if (data.opening_text) {
              setMessages((prev) => [
                ...prev,
                { role: "interviewer", text: data.opening_text },
              ])
            }
            if (data.opening_audio) {
              playAudioBase64(data.opening_audio)
            }
            if (mode.startsWith("practice")) {
              setTimeout(() => initPipeline(), 600)
            }
            break
          case "pipeline_ready":
            setPipelineMode(data.pipeline_mode)
            setIsProcessing(false)
            if (data.avatar_session?.sdp_offer) {
              setRemoteStream(new MediaStream())
            }
            setInterviewState("active")
            if (timerRef.current) clearInterval(timerRef.current)
            timerRef.current = setInterval(() => {
              setSessionTimer((prev) => prev + 1)
            }, 1000)
            break
          case "question":
            setIsProcessing(false)
            setCurrentQuestion(data.question_text)
            setCurrentTopic(data.topic)
            setProgress(data.progress)
            setMessages((prev) => [
              ...prev,
              { role: "interviewer", text: data.question_text },
            ])
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
              partialTranscriptRef.current = ""
              setMessages((prev) => {
                const filtered = prev.filter((m) => !m.isPartial)
                return [...filtered, { role: "user", text: data.text }]
              })
              addTranscriptWords(data.text)
              resetSpeechTracking()
            }
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
            setIsProcessing(false)
            break
          case "ai_interrupted":
            setAiSpeaking(false)
            aiTokenBufferRef.current = ""
            break
          case "audio_chunk":
            playAudioBase64(data.audio)
            setAiSpeaking(true)
            break
          case "evaluation":
            setIsProcessing(false)
            if (mode.startsWith("practice")) {
              updateEngagement(2000, data.score / 100)
            }
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
            setInterviewState("analyzing")
            setShowAnalyzing(true)
            break
          case "interview_complete":
            setIsProcessing(false)
            setInterviewState("complete")
            if (data.closing_text) {
              setMessages((prev) => [
                ...prev,
                { role: "interviewer", text: data.closing_text },
              ])
            }
            if (data.closing_audio) {
              playAudioBase64(data.closing_audio)
            }
            if (data.redirect_to) {
              setTimeout(() => router.replace(data.redirect_to), 2000)
            }
            break
          case "error":
            setIsProcessing(false)
            toast.error(data.message)
            break
        }
      } catch {
        toast.error("Received an invalid interview message.")
      }
    },
    [mode, router, addTranscriptWords, resetSpeechTracking, updateEngagement, updateCameraContact, setDynamicTip]
  )
  useEffect(() => {
    let cancelled = false

    async function connectWebSocket() {
      const apiBase = API_CONFIG.BASE_URL
      try {
        const ticketRes = await fetch(`${apiBase}/interview/ws-ticket`, {
          method: "POST",
          credentials: "include",
        })
        if (!ticketRes.ok) {
          const body = await ticketRes.json().catch(() => null)
          toast.error(body?.detail || body?.message || "Failed to connect to the interview session.")
          router.push("/")
          return
        }
        const { ticket } = await ticketRes.json()
        if (cancelled || !ticket) return

        const wsBase = apiBase.replace(/^http/, "ws").replace(/\/api$/, "")
        const ws = new WebSocket(`${wsBase}/api/interview/ws/video/${ticket}`)

        ws.onopen = () => {
          setIsConnected(true)
          ws.send(JSON.stringify({ type: "start_session", interview_id: sessionId }))
        }
        ws.onmessage = handleWSMessage
        ws.onclose = () => {
          setIsConnected(false)
          if (timerRef.current) clearInterval(timerRef.current)
        }
        ws.onerror = () => {
          toast.error("WebSocket connection failed")
          setIsConnected(false)
        }
        wsRef.current = ws
      } catch {
        toast.error("Failed to connect. Please try again.")
        router.push("/")
      }
    }

    connectWebSocket()
    return () => {
      cancelled = true
      wsRef.current?.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [sessionId, handleWSMessage, router])
  useEffect(() => {
    if (interviewState !== "active" || !isMicOn || !localStreamRef.current) return
    const audioStream = new MediaStream(localStreamRef.current.getAudioTracks())
    if (audioStream.getAudioTracks().length === 0) return
    vad.startListening(audioStream)
    return () => {
      stopSpeechRecording(true)
      vad.stopListening()
    }
  }, [interviewState, isMicOn, stopSpeechRecording])
  useEffect(() => {
    if (!mode.startsWith("mock")) return
    const sendAntiCheat = (eventType: string, payload: Record<string, unknown> = {}) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: "anti_cheat_event",
          event_type: eventType,
          payload,
        }))
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        sendAntiCheat("tab_switch", { visibilityState: document.visibilityState })
      }
    }
    const onBlur = () => sendAntiCheat("window_blur")
    const onFullscreen = () => {
      if (!document.fullscreenElement && interviewState === "active") {
        sendAntiCheat("fullscreen_exit")
      }
    }
    const onPaste = (event: ClipboardEvent) => {
      event.preventDefault()
      sendAntiCheat("paste_blocked")
      toast.error("Paste is disabled during mock interviews.")
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
  }, [mode, interviewState])
  const playAudioBase64 = useCallback((base64: string) => {
    audioQueueRef.current = audioQueueRef.current.then(() => new Promise<void>((resolve) => {
      try {
        const binary = atob(base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const blob = new Blob([bytes], { type: "audio/mp3" })
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
  const initPipeline = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      if (mode.startsWith("mock") && document.fullscreenEnabled && !document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {
          wsRef.current?.send(JSON.stringify({
            type: "anti_cheat_event",
            event_type: "fullscreen_request_failed",
            payload: {},
          }))
        })
      }
      wsRef.current.send(JSON.stringify({ type: "init_pipeline" }))
      setIsMicOn(true)
    }
  }, [mode])
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
    setIsVideoOn((prev) => {
      const next = !prev
      localStreamRef.current?.getVideoTracks().forEach((t) => { t.enabled = next })
      return next
    })
  }, [])
  const requestEndCall = useCallback(() => {
    setShowEndConfirm(true)
  }, [])
  const confirmEndCall = useCallback(() => {
    setShowEndConfirm(false)
    stopAllAudio()
    stopSpeechRecording(true)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_interview" }))
    }
    localStreamRef.current?.getTracks().forEach((t) => t.stop())
    setInterviewState("analyzing")
    setShowAnalyzing(true)
  }, [stopSpeechRecording, stopAllAudio])
  const cancelEndCall = useCallback(() => {
    setShowEndConfirm(false)
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
    localStream: localStreamRef.current,
  }
  if (showAnalyzing) {
    return (
      <AnalyzingOverlay
        isVisible
        interviewId={sessionId}
        onComplete={() => router.replace(`/interview/${sessionId}/report`)}
      />
    )
  }
  if (isMobile && mode.startsWith("practice")) {
    return <MobileLayout {...layoutProps} />
  }
  switch (mode) {
    case "practice-ai":
      return <PracticeAILayout {...layoutProps} />
    case "practice-voice":
      return <PracticeVoiceLayout {...layoutProps} />
    case "mock-ai":
      return <MockAILayout {...layoutProps} />
    case "mock-voice":
      return <MockVoiceLayout {...layoutProps} />
    default:
      return <PracticeAILayout {...layoutProps} />
  }
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
      <div className="w-full max-w-sm mx-4 rounded-2xl bg-[#2d2e30] border border-[#3c4043] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="p-6 text-center">
          <div className="w-14 h-14 rounded-full bg-[#ea4335]/15 flex items-center justify-center mx-auto mb-4">
            <AlertTriangle className="w-7 h-7 text-[#ea4335]" />
          </div>
          <h3 className="text-lg font-semibold text-[#e8eaed] mb-2">End this interview?</h3>
          <p className="text-sm text-[#9aa0a6] leading-relaxed">
            Are you sure you want to quit? Your progress will be saved and the AI will stop. This action cannot be undone.
          </p>
        </div>
        <div className="flex border-t border-[#3c4043]">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-3.5 text-sm font-medium text-[#8ab4f8] hover:bg-[#3c4043]/50 transition-colors"
          >
            Continue Interview
          </button>
          <div className="w-px bg-[#3c4043]" />
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-3.5 text-sm font-medium text-[#ea4335] hover:bg-[#ea4335]/10 transition-colors"
          >
            Quit
          </button>
        </div>
      </div>
    </div>
  )
}

function MeetConnectingOverlay({ state }: { state: string }) {
  return (
    <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[#202124]">
      <div className="w-12 h-12 rounded-full border-[3px] border-[#3c4043] border-t-[#8ab4f8] animate-spin mb-6" />
      <p className="text-[#9aa0a6] text-sm">
        {state === "connecting" ? "Connecting to session..." : "Starting interview..."}
      </p>
    </div>
  )
}

function MeetSidePanel({
  show, onClose, hints, dynamicTip, metrics,
}: {
  show: boolean
  onClose: () => void
  hints: string[]
  dynamicTip: string | null
  metrics: { eyeContact: string; confidence: number; emotion: string; cameraValue: number; engagementValue: number; pace: number; paceLabel: string }
}) {
  if (!show) return null
  return (
    <aside className="w-80 border-l border-[#3c4043] flex flex-col bg-[#202124] shrink-0 animate-in slide-in-from-right duration-200">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#3c4043]">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-[#8ab4f8]" />
          <h3 className="text-sm font-medium text-[#e8eaed]">AI Assistant</h3>
        </div>
        <button onClick={onClose} className="w-8 h-8 rounded-full hover:bg-[#3c4043] flex items-center justify-center text-[#9aa0a6] transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-[#9aa0a6] font-medium mb-2">Real-Time Suggestion</p>
          <div className="p-3 rounded-lg bg-[#303134] border border-[#3c4043]">
            <p className="text-sm text-[#bdc1c6] leading-relaxed italic">
              {dynamicTip ? `\u201C${dynamicTip}\u201D` : "Suggestions will appear as you speak..."}
            </p>
          </div>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wider text-[#9aa0a6] font-medium mb-2">Stuck? Try this</p>
          <ul className="space-y-2">
            {hints.length > 0 ? hints.slice(-3).map((hint, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[#bdc1c6] leading-relaxed">
                <span className="text-[#8ab4f8] mt-0.5 shrink-0">•</span>
                {hint}
              </li>
            )) : (
              <li className="text-sm text-[#5f6368] italic">Hints will appear based on the current question...</li>
            )}
          </ul>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wider text-[#9aa0a6] font-medium mb-3">Performance</p>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-[#9aa0a6]">Eye Contact</span>
                <span className="text-xs text-[#e8eaed] font-medium">{metrics.eyeContact}</span>
              </div>
              <div className="h-1 bg-[#3c4043] rounded-full overflow-hidden">
                <div className="h-full bg-[#8ab4f8] rounded-full transition-all duration-700" style={{ width: `${metrics.cameraValue}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-[#9aa0a6]">Confidence</span>
                <span className="text-xs text-[#e8eaed] font-medium tabular-nums">{metrics.confidence}%</span>
              </div>
              <div className="h-1 bg-[#3c4043] rounded-full overflow-hidden">
                <div className="h-full bg-[#81c995] rounded-full transition-all duration-700" style={{ width: `${metrics.confidence}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-[#9aa0a6]">Composure</span>
                <span className="text-xs text-[#e8eaed] font-medium">{metrics.emotion}</span>
              </div>
              <div className="flex gap-1">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className={`flex-1 h-1 rounded-full transition-all duration-500 ${i < Math.ceil(metrics.engagementValue / 20) ? "bg-[#fdd663]" : "bg-[#3c4043]"}`} />
                ))}
              </div>
            </div>
            {metrics.pace > 0 && (
              <div className="pt-2 border-t border-[#3c4043]">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-[#9aa0a6]">Pace</span>
                  <span className="text-xs text-[#e8eaed] font-medium tabular-nums">{metrics.pace} <span className="text-[#9aa0a6]">wpm</span></span>
                </div>
                <p className="text-[10px] text-[#5f6368] mt-0.5">{metrics.paceLabel} · optimal 120–160 wpm</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  )
}

function MeetBottomBar({
  timer, formatTimer, modeLabel, isMicOn, isVideoOn, onToggleMic, onToggleVideo, onEndCall,
  showCaptions, onToggleCaptions, showSidePanel, onToggleSidePanel,
}: {
  timer: number; formatTimer: (s: number) => string; modeLabel: string
  isMicOn: boolean; isVideoOn: boolean; onToggleMic: () => void; onToggleVideo: () => void; onEndCall: () => void
  showCaptions: boolean; onToggleCaptions: () => void; showSidePanel: boolean; onToggleSidePanel: () => void
}) {
  return (
    <div className="h-20 shrink-0 flex items-center justify-between px-6 z-30 bg-[#202124]">
      <div className="flex items-center gap-3 min-w-[180px]">
        <span className="text-sm font-mono tabular-nums text-[#e8eaed]">{formatTimer(timer)}</span>
        <span className="text-[#5f6368]">|</span>
        <span className="text-xs text-[#9aa0a6]">{modeLabel}</span>
      </div>
      <InterviewControls variant="meet" isMicOn={isMicOn} isVideoOn={isVideoOn} onToggleMic={onToggleMic} onToggleVideo={onToggleVideo} onEndCall={onEndCall} />
      <div className="flex items-center gap-1 min-w-[180px] justify-end">
        <button
          onClick={onToggleCaptions}
          className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${showCaptions ? "bg-[#8ab4f8] text-[#202124]" : "hover:bg-[#3c4043] text-[#e8eaed]"}`}
          title="Captions"
        >
          <Eye className="w-5 h-5" />
        </button>
        <button
          onClick={onToggleSidePanel}
          className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${showSidePanel ? "bg-[#8ab4f8] text-[#202124]" : "hover:bg-[#3c4043] text-[#e8eaed]"}`}
          title="AI Assistant"
        >
          <Brain className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}

function MeetCaptions({ show, lastUserMsg, isCapturing }: { show: boolean; lastUserMsg?: TranscriptMessage; isCapturing: boolean }) {
  if (!show || !lastUserMsg) return null
  return (
    <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-30 w-full max-w-2xl px-4">
      <div className="bg-[#202124]/95 backdrop-blur-md rounded-lg px-5 py-3 text-center shadow-xl">
        <p className="text-sm text-[#e8eaed] leading-relaxed">
          {lastUserMsg.isPartial ? (
            <>
              <span className="text-[#9aa0a6]">{lastUserMsg.text.slice(0, Math.floor(lastUserMsg.text.length * 0.4))}</span>
              <span className="text-white font-medium">{lastUserMsg.text.slice(Math.floor(lastUserMsg.text.length * 0.4))}</span>
            </>
          ) : (
            <span className="text-[#bdc1c6]">{lastUserMsg.text}</span>
          )}
          {isCapturing && <span className="inline-block w-[2px] h-[14px] bg-[#8ab4f8] ml-1 align-middle animate-pulse" />}
        </p>
      </div>
    </div>
  )
}

function MeetAITile({
  isConnected, aiSpeaking, currentQuestion, currentTopic, localStream,
}: {
  isConnected: boolean; aiSpeaking: boolean; currentQuestion: string; currentTopic: string; localStream: MediaStream | null
}) {
  return (
    <div className="flex-[2] relative rounded-xl overflow-hidden bg-[#1a1a1c]">
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className={`w-24 h-24 rounded-full bg-gradient-to-br from-[#669df6] to-[#1a73e8] flex items-center justify-center text-3xl font-medium text-white shadow-xl transition-all duration-300 ${aiSpeaking ? "ring-[3px] ring-[#669df6]/60 scale-105" : ""}`}>
          A
        </div>
        <p className="mt-3 text-[#e8eaed] text-base font-medium">Dr. Aris</p>
        <p className="text-[#9aa0a6] text-xs">AI Lead Interviewer</p>
        {aiSpeaking && (
          <div className="mt-4 w-48 opacity-40">
            <WaveformVisualizer stream={localStream} isActive variant="indigo" size="sm" />
          </div>
        )}
      </div>
      <div className="absolute top-3 left-3 z-10">
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium ${isConnected ? "bg-[#137333]/80 text-[#81c995]" : "bg-[#3c4043] text-[#9aa0a6]"}`}>
          <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? "bg-[#81c995] animate-pulse" : "bg-[#9aa0a6]"}`} />
          {isConnected ? "Connected" : "Connecting..."}
        </div>
      </div>
      <div className="absolute bottom-3 left-3 z-10">
        <span className="text-[#e8eaed] text-sm font-medium bg-[#202124]/70 backdrop-blur-sm px-2.5 py-1 rounded">Dr. Aris</span>
      </div>
      {currentQuestion && (
        <div className="absolute bottom-14 left-0 right-0 text-center px-6 z-10">
          <div className="inline-block bg-[#202124]/85 backdrop-blur-md rounded-lg px-5 py-3 max-w-xl">
            <p className="text-[10px] uppercase tracking-[0.2em] text-[#9aa0a6] mb-1">{currentTopic || "Question"}</p>
            <p className="text-[#e8eaed] text-sm leading-relaxed font-medium">{currentQuestion}</p>
          </div>
        </div>
      )}
    </div>
  )
}

function MeetSelfTile({ videoRef, isVideoOn, isMicOn }: { videoRef: React.RefObject<HTMLVideoElement | null>; isVideoOn: boolean; isMicOn: boolean }) {
  return (
    <div className="flex-1 max-w-[320px] relative rounded-xl overflow-hidden bg-[#1a1a1c]">
      {isVideoOn ? (
        <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover scale-x-[-1]" />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="w-24 h-24 rounded-full bg-[#5f6368] flex items-center justify-center text-3xl font-medium text-white">Y</div>
        </div>
      )}
      <div className="absolute bottom-3 left-3 z-10">
        <span className="text-[#e8eaed] text-sm font-medium bg-[#202124]/70 backdrop-blur-sm px-2.5 py-1 rounded">You</span>
      </div>
      {!isMicOn && (
        <div className="absolute bottom-3 right-3 z-10">
          <div className="w-7 h-7 rounded-full bg-[#ea4335] flex items-center justify-center"><MicOff className="w-3.5 h-3.5 text-white" /></div>
        </div>
      )}
    </div>
  )
}

function PracticeAILayout(props: LayoutProps) {
  const [showSidePanel, setShowSidePanel] = useState(false)
  const [showCaptions, setShowCaptions] = useState(false)
  const lastUserMsg = [...props.messages].reverse().find(m => m.role === "user")
  const eyeContactLabel = props.streamingMetrics.cameraContact.value >= 70 ? "Consistent" : props.streamingMetrics.cameraContact.value >= 40 ? "Moderate" : "Low"
  const confidenceValue = props.streamingMetrics.engagement.value
  const emotionLabel = confidenceValue >= 70 ? "Focused" : confidenceValue >= 40 ? "Neutral" : "Nervous"

  const sideMetrics = {
    eyeContact: eyeContactLabel, confidence: confidenceValue, emotion: emotionLabel,
    cameraValue: props.streamingMetrics.cameraContact.value, engagementValue: confidenceValue,
    pace: props.streamingMetrics.pace.wpm, paceLabel: props.streamingMetrics.pace.label,
  }

  return (
    <div className="h-screen flex flex-col bg-[#202124] text-white overflow-hidden relative">
      {(props.interviewState === "connecting" || props.interviewState === "ready") && <MeetConnectingOverlay state={props.interviewState} />}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 p-2 flex gap-2">
          <MeetAITile isConnected={props.isConnected} aiSpeaking={props.aiSpeaking} currentQuestion={props.currentQuestion} currentTopic={props.currentTopic} localStream={props.localStream} />
          <MeetSelfTile videoRef={props.videoRef} isVideoOn={props.isVideoOn} isMicOn={props.isMicOn} />
        </div>
        <MeetSidePanel show={showSidePanel} onClose={() => setShowSidePanel(false)} hints={props.hints} dynamicTip={props.streamingMetrics.dynamicTip} metrics={sideMetrics} />
      </div>
      <MeetCaptions show={showCaptions} lastUserMsg={lastUserMsg} isCapturing={props.isCapturing} />
      <MeetBottomBar
        timer={props.sessionTimer} formatTimer={props.formatTimer} modeLabel="Practice"
        isMicOn={props.isMicOn} isVideoOn={props.isVideoOn} onToggleMic={props.onToggleMic} onToggleVideo={props.onToggleVideo} onEndCall={props.onEndCall}
        showCaptions={showCaptions} onToggleCaptions={() => setShowCaptions(!showCaptions)}
        showSidePanel={showSidePanel} onToggleSidePanel={() => setShowSidePanel(!showSidePanel)}
      />
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}
function PracticeVoiceLayout(props: LayoutProps) {
  const [showSidePanel, setShowSidePanel] = useState(false)
  const [showCaptions, setShowCaptions] = useState(false)
  const lastUserMsg = [...props.messages].reverse().find(m => m.role === "user")
  const eyeContactLabel = props.streamingMetrics.cameraContact.value >= 70 ? "Consistent" : props.streamingMetrics.cameraContact.value >= 40 ? "Moderate" : "Low"
  const confidenceValue = props.streamingMetrics.engagement.value
  const emotionLabel = confidenceValue >= 70 ? "Focused" : confidenceValue >= 40 ? "Neutral" : "Nervous"
  const sideMetrics = {
    eyeContact: eyeContactLabel, confidence: confidenceValue, emotion: emotionLabel,
    cameraValue: props.streamingMetrics.cameraContact.value, engagementValue: confidenceValue,
    pace: props.streamingMetrics.pace.wpm, paceLabel: props.streamingMetrics.pace.label,
  }

  return (
    <div className="h-screen flex flex-col bg-[#202124] text-white overflow-hidden relative">
      {(props.interviewState === "connecting" || props.interviewState === "ready") && <MeetConnectingOverlay state={props.interviewState} />}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 p-2 flex gap-2">
          
          <div className="flex-[2] relative rounded-xl overflow-hidden bg-[#1a1a1c]">
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className={`w-24 h-24 rounded-full bg-gradient-to-br from-[#669df6] to-[#1a73e8] flex items-center justify-center text-3xl font-medium text-white shadow-xl transition-all duration-300 ${props.aiSpeaking ? "ring-[3px] ring-[#669df6]/60 scale-105" : ""}`}>A</div>
              <p className="mt-3 text-[#e8eaed] text-base font-medium">Dr. Aris</p>
              <p className="text-[#9aa0a6] text-xs">AI Lead Interviewer</p>
              <div className="mt-5 w-56 opacity-40">
                <WaveformVisualizer stream={props.localStream} isActive={props.isCapturing || props.aiSpeaking} variant="indigo" size="sm" />
              </div>
            </div>
            <div className="absolute bottom-3 left-3 z-10">
              <span className="text-[#e8eaed] text-sm font-medium bg-[#202124]/70 backdrop-blur-sm px-2.5 py-1 rounded">Dr. Aris</span>
            </div>
            {props.currentQuestion && (
              <div className="absolute bottom-14 left-0 right-0 text-center px-6 z-10">
                <div className="inline-block bg-[#202124]/85 backdrop-blur-md rounded-lg px-5 py-3 max-w-xl">
                  <p className="text-[10px] uppercase tracking-[0.2em] text-[#9aa0a6] mb-1">{props.currentTopic || "Question"}</p>
                  <p className="text-[#e8eaed] text-sm leading-relaxed font-medium">{props.currentQuestion}</p>
                </div>
              </div>
            )}
          </div>
          <MeetSelfTile videoRef={props.videoRef} isVideoOn={props.isVideoOn} isMicOn={props.isMicOn} />
        </div>
        <MeetSidePanel show={showSidePanel} onClose={() => setShowSidePanel(false)} hints={props.hints} dynamicTip={props.streamingMetrics.dynamicTip} metrics={sideMetrics} />
      </div>
      <MeetCaptions show={showCaptions} lastUserMsg={lastUserMsg} isCapturing={props.isCapturing} />
      <MeetBottomBar
        timer={props.sessionTimer} formatTimer={props.formatTimer} modeLabel="Practice · Voice"
        isMicOn={props.isMicOn} isVideoOn={props.isVideoOn} onToggleMic={props.onToggleMic} onToggleVideo={props.onToggleVideo} onEndCall={props.onEndCall}
        showCaptions={showCaptions} onToggleCaptions={() => setShowCaptions(!showCaptions)}
        showSidePanel={showSidePanel} onToggleSidePanel={() => setShowSidePanel(!showSidePanel)}
      />
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}
function MockAILayout(props: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-[#202124] text-white overflow-hidden relative">
      {(props.interviewState === "connecting") && <MeetConnectingOverlay state={props.interviewState} />}
      {props.interviewState === "ready" && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[#202124]">
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-[#669df6] to-[#1a73e8] flex items-center justify-center text-3xl font-medium text-white shadow-xl mb-6">A</div>
          <p className="text-[#e8eaed] text-lg font-medium mb-2">Ready to begin</p>
          <p className="text-[#9aa0a6] text-sm mb-8">Make sure your microphone and camera are ready</p>
          <button onClick={props.initPipeline} className="px-8 py-3 rounded-full bg-[#1a73e8] hover:bg-[#1765cc] text-white font-medium text-base transition-all shadow-xl">
            Begin Interview
          </button>
        </div>
      )}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 p-2 flex gap-2">
          <MeetAITile isConnected={props.isConnected} aiSpeaking={props.aiSpeaking} currentQuestion={props.currentQuestion} currentTopic={props.currentTopic} localStream={props.localStream} />
          <MeetSelfTile videoRef={props.videoRef} isVideoOn={props.isVideoOn} isMicOn={props.isMicOn} />
        </div>
      </div>
      <div className="h-20 shrink-0 flex items-center justify-between px-6 z-30 bg-[#202124]">
        <div className="flex items-center gap-3 min-w-[180px]">
          <Clock className="w-3.5 h-3.5 text-[#9aa0a6]" />
          <span className="text-sm font-mono tabular-nums text-[#e8eaed]">{props.formatTimer(props.sessionTimer)}</span>
          <span className="text-[#5f6368]">|</span>
          <span className="text-xs text-[#9aa0a6]">Mock Interview</span>
        </div>
        <InterviewControls variant="meet" isMicOn={props.isMicOn} isVideoOn={props.isVideoOn} onToggleMic={props.onToggleMic} onToggleVideo={props.onToggleVideo} onEndCall={props.onEndCall} endLabel="End Interview" />
        <div className="min-w-[180px]" />
      </div>
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}
function MockVoiceLayout(props: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-[#202124] text-white overflow-hidden relative">
      {(props.interviewState === "connecting") && <MeetConnectingOverlay state={props.interviewState} />}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 p-2 flex gap-2">
          <div className="flex-[2] relative rounded-xl overflow-hidden bg-[#1a1a1c]">
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className={`w-24 h-24 rounded-full bg-gradient-to-br from-[#669df6] to-[#1a73e8] flex items-center justify-center text-3xl font-medium text-white shadow-xl transition-all duration-300 ${props.aiSpeaking ? "ring-[3px] ring-[#669df6]/60 scale-105" : ""}`}>A</div>
              <p className="mt-3 text-[#e8eaed] text-base font-medium">Dr. Aris</p>
              <p className="text-[#9aa0a6] text-xs">Lead Technical Recruiter</p>
              <div className="mt-5 w-56 opacity-40">
                <WaveformVisualizer stream={props.localStream} isActive={props.aiSpeaking || props.isCapturing} variant="indigo" size="sm" />
              </div>
            </div>
            <div className="absolute bottom-3 left-3 z-10">
              <span className="text-[#e8eaed] text-sm font-medium bg-[#202124]/70 backdrop-blur-sm px-2.5 py-1 rounded">Dr. Aris</span>
            </div>
          </div>
          <MeetSelfTile videoRef={props.videoRef} isVideoOn={props.isVideoOn} isMicOn={props.isMicOn} />
        </div>
      </div>
      <div className="h-20 shrink-0 flex items-center justify-between px-6 z-30 bg-[#202124]">
        <div className="flex items-center gap-3 min-w-[180px]">
          <Clock className="w-3.5 h-3.5 text-[#9aa0a6]" />
          <span className="text-sm font-mono tabular-nums text-[#e8eaed]">{props.formatTimer(props.sessionTimer)}</span>
          <span className="text-[#5f6368]">|</span>
          <span className="text-xs text-[#9aa0a6]">Mock · Voice</span>
        </div>
        <InterviewControls variant="meet" isMicOn={props.isMicOn} isVideoOn={props.isVideoOn} onToggleMic={props.onToggleMic} onToggleVideo={props.onToggleVideo} onEndCall={props.onEndCall} endLabel="End Session" />
        <div className="min-w-[180px]" />
      </div>
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}

function MobileLayout(props: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-[var(--iv-surface)] text-[var(--iv-on-surface)] overflow-hidden relative">
      <header className="fixed top-0 w-full z-50 flex justify-between items-center px-6 h-16 bg-[var(--iv-surface)]">
        <div className="flex items-center gap-4">
          <ArrowLeft className="h-5 w-5 text-[var(--iv-primary)] cursor-pointer" onClick={props.onEndCall} />
          <h1 className="font-serif italic text-xl tracking-tight text-[var(--iv-primary)]">Interview Room</h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="bg-[var(--iv-surface-container-high)] px-3 py-1.5 rounded-full flex items-center gap-2 border border-[var(--iv-outline-variant)]/10">
            <span className={`w-2 h-2 rounded-full ${props.isCapturing ? "bg-emerald-400 animate-pulse" : "bg-[var(--iv-secondary)]"}`} />
            <span className="text-[10px] uppercase tracking-widest font-bold text-[var(--iv-primary)]">
              {props.isCapturing ? "Capturing" : "Live"}
            </span>
          </div>
        </div>
      </header>
      <main className="relative pt-16 h-screen flex flex-col justify-between overflow-hidden">
        <SelfView variant="mobile" videoRef={props.videoRef} isVideoOn={props.isVideoOn} />
        <div className="flex-1 flex flex-col justify-center px-8 text-center max-w-lg mx-auto">
          <span className="text-[10px] uppercase tracking-[0.3em] text-[var(--iv-outline)] mb-6 font-bold">
            {props.currentTopic || "Current Prompt"}
          </span>
          <h2 className="font-serif text-3xl italic text-[var(--iv-on-surface)] leading-snug">
            {props.currentQuestion
              ? `\u201C${props.currentQuestion}\u201D`
              : "\u201CWaiting for question...\u201D"}
          </h2>
          <div className="mt-12">
            <WaveformVisualizer
              stream={props.localStream}
              isActive={props.isCapturing}
              variant="emerald"
              size="sm"
            />
          </div>
        </div>
        <div className="px-6 pb-32">
          {props.messages.length > 0 && (
            <div className="bg-[var(--iv-surface-container-low)] rounded-2xl p-5 border border-[var(--iv-outline-variant)]/10 min-h-[80px]">
              <div className="flex justify-between items-center mb-3">
                <span className="text-[10px] uppercase tracking-widest text-[var(--iv-outline)] font-bold">Transcription</span>
              </div>
              <p className="text-sm text-[var(--iv-on-surface-variant)] leading-relaxed">
                {props.messages[props.messages.length - 1]?.text}
                {props.isCapturing && (
                  <span className="inline-block w-1 h-4 bg-[var(--iv-secondary)]/50 animate-pulse ml-1 align-middle" />
                )}
              </p>
            </div>
          )}
          <div className="mt-6 grid grid-cols-2 gap-4">
            <div className="bg-[var(--iv-surface-container)] p-3 rounded-xl flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-[var(--iv-surface-container-highest)] flex items-center justify-center">
                <Eye className="h-3.5 w-3.5 text-[var(--iv-tertiary)]" />
              </div>
              <div>
                <p className="text-[10px] text-[var(--iv-outline)] uppercase font-bold">Eye Contact</p>
                <p className="text-xs text-[var(--iv-on-surface)]">{props.streamingMetrics.cameraContact.label}</p>
              </div>
            </div>
            <div className="bg-[var(--iv-surface-container)] p-3 rounded-xl flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-[var(--iv-surface-container-highest)] flex items-center justify-center">
                <span className="text-[var(--iv-secondary)] text-sm">⚡</span>
              </div>
              <div>
                <p className="text-[10px] text-[var(--iv-outline)] uppercase font-bold">Pace</p>
                <p className="text-xs text-[var(--iv-on-surface)]">{props.streamingMetrics.pace.label}</p>
              </div>
            </div>
          </div>
        </div>
      </main>
      <InterviewControls
        variant="mobile"
        isMicOn={props.isMicOn}
        isVideoOn={props.isVideoOn}
        onToggleMic={props.onToggleMic}
        onToggleVideo={props.onToggleVideo}
        onEndCall={props.onEndCall}
      />
      <div className="fixed inset-0 pointer-events-none z-0 opacity-20">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,_var(--iv-primary-container)_0%,_transparent_60%)]" />
      </div>
      <EndConfirmDialog show={props.showEndConfirm} onConfirm={props.onConfirmEnd} onCancel={props.onCancelEnd} />
    </div>
  )
}
