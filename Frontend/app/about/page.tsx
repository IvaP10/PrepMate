import Link from "next/link"

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-background px-6 py-12 text-foreground">
      <div className="mx-auto max-w-2xl space-y-8">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">About</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">PrepMate</h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            A local-first interview practice workspace for resumes, mock interviews,
            technical rounds, evidence-backed reports, Performance, and Improve coaching.
          </p>
        </div>
        <div className="grid gap-3 rounded-lg border border-border bg-card p-5 text-sm">
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Version</span><span>0.1.0-alpha.1</span></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">License</span><a className="text-primary underline" href="https://www.apache.org/licenses/LICENSE-2.0" target="_blank" rel="noreferrer">Apache License 2.0</a></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Data</span><span>Stored locally; provider requests are explicit</span></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Runtime</span><span>Native macOS desktop application</span></div>
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          <Link className="rounded-md border border-border px-3 py-2 hover:bg-secondary" href="/privacy">Privacy boundary</Link>
          <Link className="rounded-md border border-border px-3 py-2 hover:bg-secondary" href="/">Back to workspace</Link>
        </div>
      </div>
    </main>
  )
}
