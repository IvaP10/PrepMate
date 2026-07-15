"use client"
import { useRef, useEffect } from "react"
interface TranscriptMessage {
  role: "interviewer" | "user"
  text: string
  isPartial?: boolean
  timestamp?: string
}
interface LiveTranscriptionProps {
  messages: TranscriptMessage[]
  isCapturing?: boolean
  isProcessing?: boolean
  variant?: "default" | "compact"
}
export function LiveTranscription({
  messages,
  isCapturing = false,
  isProcessing = false,
  variant = "default",
}: LiveTranscriptionProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      })
    }
  }, [messages])
  return (
    <div className="bg-card rounded-xl border border-border flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground">Live Transcription</h3>
        <div className="flex items-center gap-1.5">
          {isCapturing && (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-xs text-primary font-medium">
                Capturing
              </span>
            </span>
          )}
          {isProcessing && (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              <span className="text-xs text-amber-500 font-medium">
                Processing
              </span>
            </span>
          )}
        </div>
      </div>
      <div
        ref={scrollRef}
        className={`flex-1 overflow-y-auto px-4 py-3 space-y-3 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-border ${
          variant === "compact" ? "max-h-48" : "max-h-80"
        }`}
      >
        {messages.length === 0 ? (
          <p className="text-muted-foreground text-sm text-center py-8">
            Conversation will appear here...
          </p>
        ) : (
          messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-2 items-start ${
                msg.role === "user" ? "flex-row-reverse" : ""
              }`}
            >
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  msg.role === "interviewer"
                    ? "bg-primary/15 text-primary"
                    : "bg-secondary text-foreground"
                }`}
              >
                {msg.role === "interviewer" ? "AI" : "U"}
              </div>
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 ${
                  msg.role === "interviewer"
                    ? "bg-secondary"
                    : "bg-primary/10"
                } ${msg.isPartial ? "opacity-60" : "opacity-100"} transition-opacity duration-300`}
              >
                <p className="text-sm text-foreground leading-relaxed">
                  {msg.text}
                  {msg.isPartial && (
                    <span className="inline-block ml-1 w-1.5 h-3 bg-primary/60 animate-pulse rounded-sm" />
                  )}
                </p>
              </div>
            </div>
          ))
        )}
        {isProcessing && (
          <div className="flex gap-2 items-start">
            <div className="w-6 h-6 rounded-full bg-primary/15 flex items-center justify-center text-xs font-bold text-primary">
              AI
            </div>
            <div className="bg-secondary rounded-lg px-3 py-2">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
