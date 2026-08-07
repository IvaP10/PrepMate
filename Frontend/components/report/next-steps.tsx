interface ActionItem {
  title: string
  detail: string
  mode?: string
  mission_id?: string
  roadmap_node_id?: string
  exercise_id?: string
  target_mode?: string
}

interface NextStepsProps {
  steps: ActionItem[]
  onStartStep?: (step: ActionItem) => void
}

export function NextSteps({ steps, onStartStep }: NextStepsProps) {
  if (steps.length === 0) return null

  return (
    <section id="next-steps" data-report-section className="scroll-margin-top: 5rem space-y-6">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Recommended Next Steps</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Prioritize these action items before scheduling your next mock or live round:
        </p>
        
        <div className="space-y-4 mt-2">
          {steps.map((step, idx) => (
            <div key={idx} className="flex gap-4 p-4 rounded-lg border border-border/60 bg-secondary/10">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary font-mono">
                {idx + 1}
              </div>
              <div className="space-y-2">
                <h4 className="text-sm font-semibold text-foreground leading-none">{step.title}</h4>
                <p className="text-xs leading-relaxed text-muted-foreground">{step.detail}</p>
                {step.mode && step.mission_id && step.roadmap_node_id && step.exercise_id && onStartStep && (
                  <button
                    type="button"
                    onClick={() => onStartStep(step)}
                    className="rounded-md border border-primary/25 bg-primary/5 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
                  >
                    Start {step.mode.replace(/_/g, " ")}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
