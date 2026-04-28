"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { AlertCircle, Loader2, ShieldAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fetchSupportSubmissions, updateSupportSubmission } from "@/lib/api"
import { verifyToken } from "@/lib/auth"

type Submission = {
  submission_id: number
  kind: string
  status: string
  title: string | null
  message: string
  steps: string | null
  rating: number | null
  interview_id: string | null
  page_url: string | null
  admin_notes: string | null
  created_at: string | null
  updated_at: string | null
  email: string
  full_name: string
}

const statusOptions = ["open", "reviewing", "resolved", "closed"] as const

export default function AdminBugsPage() {
  const router = useRouter()
  const [submissions, setSubmissions] = useState<Submission[]>([])
  const [selectedStatus, setSelectedStatus] = useState<string>("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({})
  const [statusDraft, setStatusDraft] = useState<Record<number, string>>({})

  useEffect(() => {
    async function bootstrap() {
      const user = await verifyToken()
      if (!user) {
        router.replace("/")
        return
      }
      if (!user.is_admin) {
        setError("You do not have access to this page.")
        setLoading(false)
        return
      }
      await loadSubmissions("all")
    }
    bootstrap()
  }, [router])

  async function loadSubmissions(filter: string) {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchSupportSubmissions(filter === "all" ? undefined : filter)
      const nextSubmissions: Submission[] = data.submissions || []
      setSubmissions(nextSubmissions)
      setNotesDraft(
        Object.fromEntries(nextSubmissions.map((item) => [item.submission_id, item.admin_notes || ""]))
      )
      setStatusDraft(
        Object.fromEntries(nextSubmissions.map((item) => [item.submission_id, item.status]))
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load support inbox.")
    } finally {
      setLoading(false)
    }
  }

  async function saveSubmission(submissionId: number) {
    try {
      setSavingId(submissionId)
      setError(null)
      await updateSupportSubmission(submissionId, {
        status: statusDraft[submissionId],
        admin_notes: notesDraft[submissionId],
      })
      await loadSubmissions(selectedStatus)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update support request.")
    } finally {
      setSavingId(null)
    }
  }

  const bugCount = useMemo(
    () => submissions.filter((item) => item.kind === "bug").length,
    [submissions]
  )

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6 md:p-10">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Hidden admin route</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">Support Inbox</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Review bug reports and product feedback submitted from the dashboard.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 md:w-[340px]">
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Total</p>
              <p className="mt-2 text-2xl font-semibold">{submissions.length}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Bug Reports</p>
              <p className="mt-2 text-2xl font-semibold">{bugCount}</p>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert className="h-5 w-5 text-primary" />
            <p className="text-sm text-muted-foreground">Access is controlled by the `is_admin` flag in `UserInfo`.</p>
          </div>
          <div className="flex items-center gap-3">
            <Select
              value={selectedStatus}
              onValueChange={(value) => {
                setSelectedStatus(value)
                loadSubmissions(value)
              }}
            >
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {statusOptions.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={() => loadSubmissions(selectedStatus)}>
              Refresh
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[300px] items-center justify-center rounded-2xl border border-border bg-card">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-sm text-muted-foreground">Loading support submissions...</p>
            </div>
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-6">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
              <div>
                <p className="font-medium text-foreground">Inbox unavailable</p>
                <p className="mt-1 text-sm text-muted-foreground">{error}</p>
              </div>
            </div>
          </div>
        ) : submissions.length === 0 ? (
          <div className="flex min-h-[260px] items-center justify-center rounded-2xl border border-dashed border-border bg-card/50">
            <p className="text-sm text-muted-foreground">No support submissions yet.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {submissions.map((submission) => (
              <div key={submission.submission_id} className="rounded-2xl border border-border bg-card p-6 shadow-sm">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-border bg-secondary/40 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {submission.kind}
                      </span>
                      <span className="rounded-full border border-border bg-secondary/40 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {submission.status}
                      </span>
                    </div>
                    <h2 className="mt-3 text-lg font-semibold">
                      {submission.title || (submission.kind === "bug" ? "Untitled bug report" : "Feedback")}
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {submission.full_name} · {submission.email} · {submission.created_at ? new Date(submission.created_at).toLocaleString() : "Unknown time"}
                    </p>
                  </div>
                  <div className="min-w-[180px]">
                    <Select
                      value={statusDraft[submission.submission_id] || submission.status}
                      onValueChange={(value) =>
                        setStatusDraft((current) => ({ ...current, [submission.submission_id]: value }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {statusOptions.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
                  <div className="space-y-4">
                    <div className="rounded-xl border border-border/70 bg-secondary/10 p-4">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Message</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/85">{submission.message}</p>
                    </div>
                    {submission.steps && (
                      <div className="rounded-xl border border-border/70 bg-secondary/10 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Steps to Reproduce</p>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/85">{submission.steps}</p>
                      </div>
                    )}
                  </div>
                  <div className="space-y-4">
                    <div className="rounded-xl border border-border/70 bg-secondary/10 p-4 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-muted-foreground">Interview ID</span>
                        <span className="font-medium">{submission.interview_id || "—"}</span>
                      </div>
                      <div className="mt-3 flex items-center justify-between gap-3">
                        <span className="text-muted-foreground">Rating</span>
                        <span className="font-medium">{submission.rating || "—"}</span>
                      </div>
                      <div className="mt-3 flex items-start justify-between gap-3">
                        <span className="text-muted-foreground">Page</span>
                        <span className="max-w-[220px] text-right font-medium text-foreground/80">{submission.page_url || "—"}</span>
                      </div>
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Admin Notes</p>
                      <Textarea
                        value={notesDraft[submission.submission_id] || ""}
                        onChange={(event) =>
                          setNotesDraft((current) => ({
                            ...current,
                            [submission.submission_id]: event.target.value,
                          }))
                        }
                        rows={6}
                        placeholder="Internal triage notes, repro status, fix owner..."
                      />
                    </div>
                    <Button onClick={() => saveSubmission(submission.submission_id)} disabled={savingId === submission.submission_id}>
                      {savingId === submission.submission_id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      Save Triage Update
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
