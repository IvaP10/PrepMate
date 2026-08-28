"use client"

import { ChevronDown } from "lucide-react"

export interface ReportTranscriptTurn {
  role: "interviewer" | "candidate"
  text: string
  label?: string
}

function transcriptRole(value: unknown): ReportTranscriptTurn["role"] | null {
  const normalized = String(value || "").trim().toLowerCase()
  if (["candidate", "user", "candidate_user"].includes(normalized)) return "candidate"
  if (["interviewer", "assistant", "ai", "coach"].includes(normalized)) return "interviewer"
  return null
}

export function normalizeReportTranscript(
  value: unknown,
  fallbackQuestions: Array<Record<string, any>> = [],
): ReportTranscriptTurn[] {
  const turns: ReportTranscriptTurn[] = []
  const seen = new Set<string>()

  const append = (roleValue: unknown, textValue: unknown, labelValue?: unknown) => {
    const role = transcriptRole(roleValue)
    const text = String(textValue || "").trim()
    if (!role || !text) return
    const key = `${role}:${text.replace(/\s+/g, " ").toLowerCase()}`
    if (seen.has(key)) return
    seen.add(key)
    const label = String(labelValue || "").trim()
    turns.push({ role, text, ...(label ? { label } : {}) })
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      if (!item || typeof item !== "object") continue
      const row = item as Record<string, any>
      append(
        row.role || row.speaker,
        row.text || row.content || row.transcript || row.response,
        row.label,
      )
    }
  }

  for (const question of fallbackQuestions) {
    append("interviewer", question.question, "Question")
    append(
      "candidate",
      question.transcript || question.response || question.user_answer,
      "Answer",
    )
  }

  return turns
}

export function ReportTranscript({ turns }: { turns: ReportTranscriptTurn[] }) {
  if (!turns.length) return null

  return (
    <section id="transcript" data-report-section className="scroll-mt-8 rounded-lg border border-border bg-card p-5">
      <h2 className="text-base font-bold">Transcript</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        The persisted interviewer and candidate turns used by this report.
      </p>
      <details className="group mt-4 rounded-md border border-border bg-background" data-report-transcript>
        <summary
          className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold"
          data-report-transcript-toggle
        >
          <span>View full transcript</span>
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <div className="space-y-4 border-t border-border px-4 py-4">
          {turns.map((turn, index) => (
            <div key={`${turn.role}-${index}-${turn.text.slice(0, 32)}`} className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-4">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                {turn.label || (turn.role === "candidate" ? "Candidate" : "Interviewer")}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{turn.text}</p>
            </div>
          ))}
        </div>
      </details>
    </section>
  )
}
