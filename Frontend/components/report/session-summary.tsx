interface SessionSummaryProps {
  summary: string
  interviewerSignal?: string
}

export function SessionSummary({ summary, interviewerSignal }: SessionSummaryProps) {
  return (
    <section id="summary" data-report-section className="scroll-margin-top: 5rem">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">What this means</h2>
        <div className="pl-4 border-l-2 border-primary/20 text-muted-foreground leading-relaxed text-[0.96rem] space-y-3">
          <p className="whitespace-pre-wrap">{summary}</p>
          {interviewerSignal && (
            <p className="font-medium text-foreground/90 italic">{interviewerSignal}</p>
          )}
        </div>
      </div>
    </section>
  )
}
