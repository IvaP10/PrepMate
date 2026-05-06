"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Code2, LayoutPanelLeft, Loader2, Play, ShieldAlert, SquareTerminal } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { API_CONFIG } from "@/lib/config"

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false })
const Excalidraw = dynamic(() => import("@excalidraw/excalidraw").then((mod) => mod.Excalidraw), { ssr: false })

type Round = {
  round_id: string
  round_type: "dsa" | "system_design" | "debugging"
  language: "python" | "javascript" | "java" | null
  prompt: string
  starter_code: string | null
  whiteboard_json: any
  status: string
}

type RunResult = {
  stdout: string
  stderr: string
  exit_code: number | null
  runtime_ms: number
}

const labels: Record<Round["round_type"], string> = {
  dsa: "DSA",
  system_design: "System Design",
  debugging: "Debugging",
}

export default function TechnicalInterviewPage() {
  const params = useParams()
  const router = useRouter()
  const interviewId = params.id as string
  const [rounds, setRounds] = useState<Round[]>([])
  const [activeRoundId, setActiveRoundId] = useState("")
  const [codeByRound, setCodeByRound] = useState<Record<string, string>>({})
  const [languageByRound, setLanguageByRound] = useState<Record<string, string>>({})
  const [output, setOutput] = useState<RunResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const saveWhiteboardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const activeRound = useMemo(
    () => rounds.find((round) => round.round_id === activeRoundId) || rounds[0],
    [rounds, activeRoundId]
  )

  const recordAntiCheat = useCallback(async (eventType: string, payload: Record<string, unknown> = {}) => {
    try {
      await fetch(`${API_CONFIG.BASE_URL}/technical/anti-cheat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interview_id: interviewId, event_type: eventType, payload }),
      })
    } catch {
    }
  }, [interviewId])

  useEffect(() => {
    async function loadRounds() {
      try {
        const response = await fetch(`${API_CONFIG.BASE_URL}/technical/sessions/${interviewId}/rounds`, {
          credentials: "include",
        })
        if (!response.ok) throw new Error("Failed to load technical rounds")
        const data = await response.json()
        setRounds(data.rounds || [])
        setActiveRoundId(data.rounds?.[0]?.round_id || "")
        const code: Record<string, string> = {}
        const languages: Record<string, string> = {}
        ;(data.rounds || []).forEach((round: Round) => {
          code[round.round_id] = round.starter_code || ""
          languages[round.round_id] = round.language || "python"
        })
        setCodeByRound(code)
        setLanguageByRound(languages)
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to load technical mode.")
      } finally {
        setLoading(false)
      }
    }
    loadRounds()
  }, [interviewId])

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") void recordAntiCheat("tab_switch")
    }
    const onBlur = () => void recordAntiCheat("window_blur")
    const onFullscreen = () => {
      if (!document.fullscreenElement) void recordAntiCheat("fullscreen_exit")
    }
    const onPaste = (event: ClipboardEvent) => {
      event.preventDefault()
      void recordAntiCheat("paste_blocked")
      toast.error("Paste is disabled in technical mode.")
    }
    document.addEventListener("visibilitychange", onVisibility)
    document.addEventListener("fullscreenchange", onFullscreen)
    document.addEventListener("paste", onPaste)
    window.addEventListener("blur", onBlur)
    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      document.removeEventListener("fullscreenchange", onFullscreen)
      document.removeEventListener("paste", onPaste)
      window.removeEventListener("blur", onBlur)
    }
  }, [recordAntiCheat])

  const lockFullscreen = async () => {
    try {
      await document.documentElement.requestFullscreen()
    } catch {
      await recordAntiCheat("fullscreen_request_failed")
      toast.error("Fullscreen lock failed. Continue without switching tabs.")
    }
  }

  const runCode = async () => {
    if (!activeRound || activeRound.round_type === "system_design") return
    setRunning(true)
    setOutput(null)
    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${activeRound.round_id}/run`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          language: languageByRound[activeRound.round_id] || activeRound.language || "python",
          code: codeByRound[activeRound.round_id] || "",
          stdin: "",
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "Code execution failed")
      setOutput(data)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Code execution failed")
    } finally {
      setRunning(false)
    }
  }

  const saveWhiteboard = (elements: readonly any[], appState: any, files: any) => {
    if (!activeRound || activeRound.round_type !== "system_design") return
    if (saveWhiteboardTimerRef.current) clearTimeout(saveWhiteboardTimerRef.current)
    saveWhiteboardTimerRef.current = setTimeout(async () => {
      await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${activeRound.round_id}/whiteboard`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ whiteboard_json: { elements, appState, files } }),
      }).catch(() => undefined)
    }, 900)
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-border px-5">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => router.push(`/interview/${interviewId}?mode=mock-voice`)}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-sm font-semibold">Technical Interview</h1>
            <p className="text-xs text-muted-foreground">DSA, system design, debugging</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" onClick={lockFullscreen}>
            <ShieldAlert className="h-4 w-4" />
            Lock
          </Button>
          {activeRound?.round_type !== "system_design" && (
            <Button className="gap-2" onClick={runCode} disabled={running}>
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run
            </Button>
          )}
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-[280px_1fr]">
        <aside className="border-r border-border bg-card/50 p-4">
          <div className="space-y-2">
            {rounds.map((round) => (
              <button
                key={round.round_id}
                onClick={() => {
                  setActiveRoundId(round.round_id)
                  setOutput(null)
                }}
                className={`flex w-full items-center gap-3 rounded-lg border px-3 py-3 text-left text-sm transition-colors ${
                  activeRound?.round_id === round.round_id
                    ? "border-primary/40 bg-primary/10 text-foreground"
                    : "border-border/45 bg-background hover:bg-secondary/60"
                }`}
              >
                {round.round_type === "system_design" ? <LayoutPanelLeft className="h-4 w-4" /> : <Code2 className="h-4 w-4" />}
                <span>{labels[round.round_type]}</span>
              </button>
            ))}
          </div>
          <div className="mt-5 rounded-lg border border-border bg-background p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Prompt</p>
            <p className="mt-2 text-sm leading-6">{activeRound?.prompt}</p>
          </div>
        </aside>

        <section className="flex min-h-0 flex-col">
          {activeRound?.round_type === "system_design" ? (
            <div className="min-h-0 flex-1">
              <Excalidraw
                initialData={activeRound.whiteboard_json || undefined}
                onChange={saveWhiteboard}
              />
            </div>
          ) : (
            <>
              <div className="flex h-11 items-center justify-between border-b border-border px-4">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <SquareTerminal className="h-4 w-4" />
                  <span>{labels[activeRound?.round_type || "dsa"]}</span>
                </div>
                <select
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                  value={languageByRound[activeRound?.round_id || ""] || "python"}
                  onChange={(event) => activeRound && setLanguageByRound((prev) => ({
                    ...prev,
                    [activeRound.round_id]: event.target.value,
                  }))}
                >
                  <option value="python">Python</option>
                  <option value="javascript">JavaScript</option>
                  <option value="java">Java</option>
                </select>
              </div>
              <div className="min-h-0 flex-1">
                <MonacoEditor
                  height="100%"
                  theme="vs-dark"
                  language={languageByRound[activeRound?.round_id || ""] || "python"}
                  value={codeByRound[activeRound?.round_id || ""] || ""}
                  onChange={(value) => activeRound && setCodeByRound((prev) => ({
                    ...prev,
                    [activeRound.round_id]: value || "",
                  }))}
                  options={{ minimap: { enabled: false }, fontSize: 14 }}
                />
              </div>
              <div className="h-44 border-t border-border bg-zinc-950 p-4 font-mono text-xs text-zinc-100">
                <p className="mb-2 text-zinc-400">Output</p>
                {output ? (
                  <pre className="whitespace-pre-wrap">
                    {output.stdout || output.stderr || "(no output)"}
                    {`\nexit=${output.exit_code ?? "unknown"} runtime=${output.runtime_ms}ms`}
                  </pre>
                ) : (
                  <p className="text-zinc-500">Run code to see stdout, stderr, and exit code.</p>
                )}
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  )
}
