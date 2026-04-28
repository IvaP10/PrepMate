"use client"
import { useRef, useEffect } from "react"
import { Camera } from "lucide-react"
interface SelfViewProps {
  variant?: "overlay" | "sidebar" | "mobile"
  videoRef?: React.RefObject<HTMLVideoElement | null>
  isVideoOn?: boolean
}
export function SelfView({ variant = "overlay", videoRef, isVideoOn = true }: SelfViewProps) {
  const localRef = useRef<HTMLVideoElement>(null)
  const activeRef = videoRef || localRef
  useEffect(() => {
    if (!videoRef && activeRef.current && !activeRef.current.srcObject) {
      navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        .then(stream => {
          if (activeRef.current) activeRef.current.srcObject = stream
        })
        .catch(() => {})
    }
  }, [videoRef, activeRef])
  if (variant === "mobile") {
    return (
      <div className="absolute top-20 right-6 z-40">
        <div className="w-24 h-32 rounded-xl overflow-hidden bg-[var(--iv-surface-container-high)] border border-[var(--iv-outline-variant)]/20 shadow-2xl">
          {isVideoOn ? (
            <video ref={activeRef} autoPlay playsInline muted className="w-full h-full object-cover opacity-80 grayscale contrast-125" />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-[var(--iv-surface-container-high)]">
              <Camera className="h-4 w-4 text-[var(--iv-on-surface-variant)]" />
            </div>
          )}
          <div className="absolute bottom-1 right-1">
            <Camera className="h-3 w-3 text-[var(--iv-secondary)]" />
          </div>
        </div>
      </div>
    )
  }
  if (variant === "sidebar") {
    return (
      <div className="relative rounded-xl overflow-hidden aspect-video bg-[var(--iv-surface-container-lowest)] group cursor-pointer">
        {isVideoOn ? (
          <video ref={activeRef} autoPlay playsInline muted className="w-full h-full object-cover opacity-40 grayscale group-hover:grayscale-0 group-hover:opacity-100 transition-all duration-700" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Camera className="h-8 w-8 text-[var(--iv-on-surface-variant)]" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent" />
        <div className="absolute bottom-3 left-3 flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-[var(--iv-primary-dim)] animate-pulse" />
          <span className="font-sans text-[10px] uppercase tracking-widest text-[var(--iv-on-surface-variant)]">Self View</span>
        </div>
      </div>
    )
  }
  return (
    <div className="absolute top-6 right-6 w-48 md:w-64 aspect-video rounded-xl overflow-hidden border-2 border-white/10 shadow-2xl bg-[var(--iv-surface-container-high)] transition-transform hover:scale-105 duration-300 z-10">
      {isVideoOn ? (
        <video ref={activeRef} autoPlay playsInline muted className="w-full h-full object-cover" />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <Camera className="h-8 w-8 text-[var(--iv-on-surface-variant)]" />
        </div>
      )}
      <div className="absolute bottom-2 left-2 px-2 py-0.5 bg-black/40 backdrop-blur-md rounded text-[10px] text-white/80 font-medium">
        You
      </div>
    </div>
  )
}
