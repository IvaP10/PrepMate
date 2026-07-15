"use client"
import { Mic, MicOff, Video, VideoOff, PhoneOff, Captions } from "lucide-react"
interface InterviewControlsProps {
  variant?: "floating" | "bar" | "mobile" | "meet"
  isMicOn: boolean
  isVideoOn: boolean
  onToggleMic: () => void
  onToggleVideo: () => void
  onEndCall: () => void
  captionsEnabled?: boolean
  onToggleCaptions?: () => void
  endLabel?: string
  cameraLocked?: boolean
}
export function InterviewControls({
  variant = "bar",
  isMicOn,
  isVideoOn,
  onToggleMic,
  onToggleVideo,
  onEndCall,
  captionsEnabled = false,
  onToggleCaptions,
  endLabel = "End Interview",
  cameraLocked = false,
}: InterviewControlsProps) {
  const toggleCaptions = onToggleCaptions || (() => {})
  const captionsTitle = captionsEnabled ? "Hide captions" : "Show captions"
  if (variant === "meet") {
    return (
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleMic}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 ${
            isMicOn
              ? "bg-secondary hover:bg-accent text-foreground"
              : "bg-destructive hover:bg-destructive/90 text-destructive-foreground"
          }`}
          title={isMicOn ? "Turn off microphone" : "Turn on microphone"}
        >
          {isMicOn ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
        </button>
        <button
          onClick={onToggleVideo}
          disabled={cameraLocked}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 ${
            isVideoOn
              ? "bg-secondary hover:bg-accent text-foreground"
              : "bg-destructive hover:bg-destructive/90 text-destructive-foreground"
          }`}
          title={cameraLocked ? "Camera is required during the interview" : isVideoOn ? "Turn off camera" : "Turn on camera"}
        >
          {isVideoOn ? <Video className="h-5 w-5" /> : <VideoOff className="h-5 w-5" />}
        </button>
        <button
          onClick={toggleCaptions}
          className="w-12 h-12 rounded-full bg-secondary hover:bg-accent text-foreground flex items-center justify-center transition-all duration-200"
          title={captionsTitle}
          aria-pressed={captionsEnabled}
        >
          <Captions className="h-5 w-5" />
        </button>
        <div className="w-px h-8 bg-border mx-1" />
        <button
          onClick={onEndCall}
          aria-label={endLabel}
          title={endLabel}
          className="h-12 px-5 rounded-full bg-destructive hover:bg-destructive/90 text-destructive-foreground flex items-center gap-2 transition-all duration-200"
        >
          <PhoneOff className="h-5 w-5" />
        </button>
      </div>
    )
  }
  if (variant === "mobile") {
    return (
      <nav className="fixed bottom-0 left-0 w-full h-24 flex justify-around items-center px-8 pb-6 bg-[var(--iv-surface-container-low)]/90 backdrop-blur-xl z-50 rounded-t-[32px]">
        <button onClick={onToggleMic} className="flex items-center justify-center text-[var(--iv-primary)] w-12 h-12 hover:bg-[var(--iv-surface-container-high)] transition-all active:scale-90 rounded-full">
          {isMicOn ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
        </button>
        <button onClick={onToggleVideo} className="flex items-center justify-center text-[var(--iv-primary)] w-12 h-12 hover:bg-[var(--iv-surface-container-high)] transition-all active:scale-90 rounded-full">
          {isVideoOn ? <Video className="h-5 w-5" /> : <VideoOff className="h-5 w-5" />}
        </button>
        <button onClick={toggleCaptions} aria-pressed={captionsEnabled} className="flex items-center justify-center text-[var(--iv-primary)] w-12 h-12 hover:bg-[var(--iv-surface-container-high)] transition-all active:scale-90 rounded-full">
          <Captions className="h-5 w-5" />
        </button>
        <button onClick={onEndCall} className="flex items-center justify-center bg-[var(--iv-error)] text-[var(--iv-on-error)] rounded-full w-12 h-12 hover:opacity-90 transition-all active:scale-90">
          <PhoneOff className="h-5 w-5" />
        </button>
      </nav>
    )
  }
  if (variant === "floating") {
    return (
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-4 bg-card/85 backdrop-blur-xl px-6 py-4 rounded-full border border-border shadow-2xl z-20">
        <ControlButton icon={isMicOn ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />} onClick={onToggleMic} label={isMicOn ? "Mic" : "Muted"} floating />
        <ControlButton icon={isVideoOn ? <Video className="h-5 w-5" /> : <VideoOff className="h-5 w-5" />} onClick={onToggleVideo} label="Video" floating />
        <ControlButton icon={<Captions className="h-5 w-5" />} onClick={toggleCaptions} label={captionsEnabled ? "Captions on" : "Captions"} floating />
        <div className="w-px h-8 bg-white/10 mx-2 self-center" />
        <button onClick={onEndCall} className="flex flex-col items-center gap-1 group">
          <div className="px-6 h-12 rounded-full bg-[var(--iv-error)]/20 hover:bg-[var(--iv-error)]/30 flex items-center justify-center transition-all border border-[var(--iv-error)]/30 gap-2">
            <PhoneOff className="h-5 w-5 text-[var(--iv-error)]" />
            <span className="text-sm font-bold text-[var(--iv-error)] tracking-wide">{endLabel}</span>
          </div>
          <span className="text-xs text-muted-foreground font-medium">Exit</span>
        </button>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-3 bg-[var(--iv-surface-container-high)] p-2 rounded-full shadow-2xl">
      <BarButton icon={isMicOn ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />} onClick={onToggleMic} />
      <BarButton icon={isVideoOn ? <Video className="h-5 w-5" /> : <VideoOff className="h-5 w-5" />} onClick={onToggleVideo} />
      <BarButton icon={<Captions className="h-5 w-5" />} onClick={toggleCaptions} />
      <div className="w-px h-6 bg-[var(--iv-outline-variant)] mx-1" />
      <button onClick={onEndCall} className="w-12 h-12 flex items-center justify-center rounded-full bg-destructive/10 text-[var(--iv-error)] hover:bg-destructive/15 transition-all active:scale-90">
        <PhoneOff className="h-5 w-5" />
      </button>
    </div>
  )
}
function ControlButton({ icon, onClick, label, floating }: { icon: React.ReactNode; onClick: () => void; label: string; floating?: boolean }) {
  if (floating) {
    return (
      <button onClick={onClick} className="flex flex-col items-center gap-1 group">
        <div className="w-12 h-12 rounded-full bg-secondary group-hover:bg-accent flex items-center justify-center transition-all border border-border text-foreground group-hover:text-foreground">
          {icon}
        </div>
        <span className="text-xs text-muted-foreground font-medium">{label}</span>
      </button>
    )
  }
  return null
}
function BarButton({ icon, onClick }: { icon: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="w-12 h-12 flex items-center justify-center rounded-full bg-[var(--iv-surface-container-highest)] text-[var(--iv-on-surface-variant)] hover:text-[var(--iv-primary)] hover:bg-[var(--iv-surface-bright)] transition-all active:scale-90">
      {icon}
    </button>
  )
}
