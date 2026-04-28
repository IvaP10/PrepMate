"use client"
import { useRef, useEffect, useState } from "react"
import { Camera, Wifi, WifiOff } from "lucide-react"
interface AvatarViewProps {
  remoteStream: MediaStream | null
  isConnected: boolean
  avatarName?: string
  avatarTitle?: string
  mode?: "practice" | "mock"
  fallbackMode?: boolean
  audioVisualizerActive?: boolean
}
export function AvatarView({
  remoteStream,
  isConnected,
  avatarName = "Dr. Aris",
  avatarTitle = "AI Lead Interviewer",
  mode = "practice",
  fallbackMode = false,
  audioVisualizerActive = false,
}: AvatarViewProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [isVideoReady, setIsVideoReady] = useState(false)
  useEffect(() => {
    if (videoRef.current && remoteStream) {
      videoRef.current.srcObject = remoteStream
      videoRef.current.play().catch(() => {})
    }
  }, [remoteStream])
  useEffect(() => {
    if (!audioVisualizerActive || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    let animFrame: number
    const drawWaveform = () => {
      const w = canvas.width
      const h = canvas.height
      ctx.fillStyle = "rgba(0, 0, 0, 0.1)"
      ctx.fillRect(0, 0, w, h)
      ctx.strokeStyle = "#6366f1"
      ctx.lineWidth = 2
      ctx.beginPath()
      const time = Date.now() / 1000
      for (let x = 0; x < w; x++) {
        const y =
          h / 2 +
          Math.sin(x * 0.03 + time * 3) * 15 +
          Math.sin(x * 0.07 + time * 5) * 8 +
          Math.sin(x * 0.01 + time * 2) * 20
        if (x === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
      ctx.strokeStyle = "#a855f7"
      ctx.lineWidth = 1.5
      ctx.beginPath()
      for (let x = 0; x < w; x++) {
        const y =
          h / 2 +
          Math.sin(x * 0.04 + time * 4) * 12 +
          Math.cos(x * 0.06 + time * 3) * 10
        if (x === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
      animFrame = requestAnimationFrame(drawWaveform)
    }
    drawWaveform()
    return () => cancelAnimationFrame(animFrame)
  }, [audioVisualizerActive])
  const isMock = mode === "mock"
  return (
    <div
      className={`relative overflow-hidden bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 ${
        isMock ? "w-full h-full" : "rounded-2xl aspect-video"
      }`}
    >
      {isMock && (
        <div
          className="absolute inset-0 pointer-events-none z-10"
          style={{
            boxShadow: "inset 0 0 100px rgba(0,0,0,0.6)",
          }}
        />
      )}
      {!fallbackMode && remoteStream ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          onLoadedData={() => setIsVideoReady(true)}
          className={`w-full h-full object-cover ${
            isVideoReady ? "opacity-100" : "opacity-0"
          } transition-opacity duration-500`}
        />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-2xl">
            <Camera className="w-10 h-10 text-white" />
          </div>
          <div className="text-center">
            <p className="text-white/90 font-medium text-lg">{avatarName}</p>
            <p className="text-white/50 text-sm">{avatarTitle}</p>
          </div>
          {audioVisualizerActive && (
            <canvas
              ref={canvasRef}
              width={300}
              height={80}
              className="mt-4 rounded-lg opacity-80"
            />
          )}
        </div>
      )}
      {!isVideoReady && !fallbackMode && remoteStream && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="w-16 h-16 rounded-full bg-white/5 animate-pulse" />
            <div className="h-3 w-32 bg-white/10 rounded animate-pulse" />
          </div>
        </div>
      )}
      <div className="absolute top-3 left-3 z-20 flex items-center gap-2">
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-md ${
            isConnected
              ? "bg-emerald-500/20 text-emerald-400"
              : "bg-white/10 text-white/50"
          }`}
        >
          {isConnected ? (
            <Wifi className="w-3 h-3" />
          ) : (
            <WifiOff className="w-3 h-3" />
          )}
          {isConnected ? "Live" : "Connecting..."}
        </div>
      </div>
      {!isMock && (
        <div className="absolute bottom-3 left-3 z-20">
          <div className="bg-black/60 backdrop-blur-md rounded-lg px-3 py-1.5">
            <p className="text-white text-sm font-medium">{avatarName}</p>
            <p className="text-white/50 text-xs">{avatarTitle}</p>
          </div>
        </div>
      )}
    </div>
  )
}
