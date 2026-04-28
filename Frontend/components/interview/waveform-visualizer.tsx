"use client"
import { useRef, useEffect } from "react"
interface WaveformVisualizerProps {
  stream?: MediaStream | null
  isActive?: boolean
  variant?: "indigo" | "emerald" | "amber"
  size?: "sm" | "md" | "lg"
}
const COLORS = {
  indigo: { primary: "#6366f1", secondary: "#a855f7" },
  emerald: { primary: "#10b981", secondary: "#34d399" },
  amber: { primary: "#f59e0b", secondary: "#fbbf24" },
}
const SIZES = { sm: 40, md: 60, lg: 80 }
export function WaveformVisualizer({
  stream,
  isActive = false,
  variant = "indigo",
  size = "md",
}: WaveformVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const animRef = useRef<number | null>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    if (stream && isActive) {
      const audioCtx = new AudioContext()
      const source = audioCtx.createMediaStreamSource(stream)
      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.8
      source.connect(analyser)
      audioCtxRef.current = audioCtx
      analyserRef.current = analyser
      const dataArray = new Uint8Array(analyser.frequencyBinCount)
      const colors = COLORS[variant]
      const draw = () => {
        analyser.getByteFrequencyData(dataArray)
        const w = canvas.width
        const h = canvas.height
        ctx.clearRect(0, 0, w, h)
        const barCount = 32
        const barWidth = w / barCount - 1
        const centerY = h / 2
        for (let i = 0; i < barCount; i++) {
          const dataIndex = Math.floor((i / barCount) * dataArray.length)
          const value = dataArray[dataIndex] / 255
          const barHeight = Math.max(2, value * centerY * 0.9)
          const gradient = ctx.createLinearGradient(0, centerY - barHeight, 0, centerY + barHeight)
          gradient.addColorStop(0, colors.primary + "cc")
          gradient.addColorStop(0.5, colors.secondary + "66")
          gradient.addColorStop(1, colors.primary + "cc")
          ctx.fillStyle = gradient
          ctx.fillRect(
            i * (barWidth + 1),
            centerY - barHeight,
            barWidth,
            barHeight * 2
          )
        }
        animRef.current = requestAnimationFrame(draw)
      }
      draw()
    } else {
      const w = canvas.width
      const h = canvas.height
      const colors = COLORS[variant]
      const drawIdle = () => {
        ctx.clearRect(0, 0, w, h)
        const time = Date.now() / 1000
        const centerY = h / 2
        ctx.strokeStyle = colors.primary + "40"
        ctx.lineWidth = 1.5
        ctx.beginPath()
        for (let x = 0; x < w; x++) {
          const y = centerY + Math.sin(x * 0.05 + time * 2) * 3
          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.stroke()
        animRef.current = requestAnimationFrame(drawIdle)
      }
      drawIdle()
    }
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
      if (audioCtxRef.current) {
        audioCtxRef.current.close()
        audioCtxRef.current = null
      }
    }
  }, [stream, isActive, variant])
  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={SIZES[size]}
      className="w-full rounded-lg"
    />
  )
}
