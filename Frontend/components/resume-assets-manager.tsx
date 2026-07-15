"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Check, FileText, Loader2, Plus, RefreshCw, Target, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  activateResumeVersion,
  createJobProfile,
  deleteJobProfile,
  fetchJobProfiles,
  fetchResumeVersions,
  getResume,
  selectJobProfile,
  updateResumeFacts,
  type JobProfile,
  type ResumeFact,
  type ResumeVersion,
} from "@/lib/api"
import type { ResumeData } from "@/types/resume"

export function ResumeAssetsManager({
  refreshKey,
  onResumeActivated,
  onActiveResumeId,
}: {
  refreshKey?: number
  onResumeActivated?: (resume: ResumeData) => void
  onActiveResumeId?: (resumeId: string | null) => void
}) {
  const [resumes, setResumes] = useState<ResumeVersion[]>([])
  const [activeResumeId, setActiveResumeId] = useState<string | null>(null)
  const [reviewResumeId, setReviewResumeId] = useState<string | null>(null)
  const [jobs, setJobs] = useState<JobProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [busyId, setBusyId] = useState<string | number | null>(null)
  const [showJobForm, setShowJobForm] = useState(false)
  const [jobDraft, setJobDraft] = useState({ role: "", company: "", experience_level: "mid", tech_stack: "", job_description: "" })
  const [corrections, setCorrections] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    const [resumeResult, jobResult] = await Promise.allSettled([fetchResumeVersions(), fetchJobProfiles()])
    if (resumeResult.status === "fulfilled") {
      setResumes(resumeResult.value.resumes)
      setActiveResumeId(resumeResult.value.active_resume_id)
      setReviewResumeId((current) => current && resumeResult.value.resumes.some((item) => item.resume_id === current)
        ? current
        : resumeResult.value.active_resume_id)
      onActiveResumeId?.(resumeResult.value.active_resume_id)
    }
    if (jobResult.status === "fulfilled") setJobs(jobResult.value)
    const failures = [resumeResult, jobResult].filter((item) => item.status === "rejected") as PromiseRejectedResult[]
    if (failures.length) setError(failures.map((item) => item.reason?.message || "Could not load saved assets").join(" "))
    setLoading(false)
  }, [onActiveResumeId])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const activeResume = useMemo(() => resumes.find((item) => item.resume_id === activeResumeId) || null, [activeResumeId, resumes])
  const reviewResume = useMemo(() => resumes.find((item) => item.resume_id === reviewResumeId) || activeResume, [activeResume, reviewResumeId, resumes])
  const pendingFacts = useMemo(
    () => (reviewResume?.facts || []).filter((fact) => String(fact.status || "pending") === "pending"),
    [reviewResume],
  )

  const activate = async (resumeId: string) => {
    setBusyId(resumeId)
    try {
      await activateResumeVersion(resumeId)
      setActiveResumeId(resumeId)
      onActiveResumeId?.(resumeId)
      const current = await getResume()
      onResumeActivated?.(current)
      await load()
      toast.success("Active resume updated")
    } catch (err: any) {
      toast.error(err?.message || "Failed to activate resume")
    } finally {
      setBusyId(null)
    }
  }

  const decideFact = async (fact: ResumeFact, action: "confirm" | "correct" | "reject") => {
    if (!reviewResume?.resume_id) return
    setBusyId(fact.fact_id)
    try {
      const updated = await updateResumeFacts(reviewResume.resume_id, [{
        fact_id: fact.fact_id,
        action,
        ...(action === "correct" ? { corrected_value: corrections[fact.fact_id] } : {}),
      }])
      setReviewResumeId(updated.resume_id)
      await load()
      if (updated.parent_resume_id) toast.info("A new resume version was created so prior attempts stay unchanged.")
    } catch (err: any) {
      toast.error(err?.message || "Failed to update resume fact")
    } finally {
      setBusyId(null)
    }
  }

  const createTarget = async () => {
    if (!jobDraft.role.trim() || !jobDraft.job_description.trim()) return
    setBusyId("new-job")
    try {
      const created = await createJobProfile({
        role: jobDraft.role.trim(),
        company: jobDraft.company.trim(),
        experience_level: jobDraft.experience_level,
        tech_stack: jobDraft.tech_stack.split(",").map((item) => item.trim()).filter(Boolean),
        job_description: jobDraft.job_description.trim(),
      })
      await selectJobProfile(created.profile_id)
      setJobDraft({ role: "", company: "", experience_level: "mid", tech_stack: "", job_description: "" })
      setShowJobForm(false)
      await load()
      toast.success("Job target saved")
    } catch (err: any) {
      toast.error(err?.message || "Failed to save job target")
    } finally {
      setBusyId(null)
    }
  }

  const removeTarget = async (profileId: number) => {
    setBusyId(profileId)
    try {
      await deleteJobProfile(profileId)
      await load()
    } catch (err: any) {
      toast.error(err?.message || "Failed to delete job target")
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="mb-6 grid gap-5 xl:grid-cols-2">
      <section className="dashboard-card">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-foreground">Resume versions</h3>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={() => void load()} aria-label="Refresh saved assets"><RefreshCw className="h-4 w-4" /></Button>
        </div>
        {loading ? (
          <div className="flex min-h-28 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-primary" /></div>
        ) : resumes.length ? (
          <div className="mt-4 space-y-2">
            {resumes.map((resume) => (
              <div key={resume.resume_id} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-secondary/20 p-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">{resume.source_filename || `Resume version ${resume.version_number}`}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Version {resume.version_number} · {resume.confirmation_status?.replace(/_/g, " ") || "review pending"}
                    {resume.immutable ? " · locked to prior attempts" : ""}
                  </p>
                </div>
                {resume.resume_id === activeResumeId ? (
                  <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-300"><Check className="h-3 w-3" /> Active</span>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busyId === resume.resume_id}
                    onClick={() => resume.confirmation_status === "confirmed" ? void activate(resume.resume_id) : setReviewResumeId(resume.resume_id)}
                  >
                    {busyId === resume.resume_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : resume.confirmation_status === "confirmed" ? "Use" : "Review"}
                  </Button>
                )}
              </div>
            ))}
          </div>
        ) : <p className="mt-4 text-sm text-muted-foreground">Upload a resume to create version 1.</p>}

        {pendingFacts.length > 0 && (
          <div className="mt-5 border-t border-border/60 pt-4">
            <p className="text-sm font-semibold text-foreground">Review uncertain facts</p>
            <div className="mt-3 space-y-3">
              {pendingFacts.slice(0, 4).map((fact) => (
                <div key={fact.fact_id} className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3">
                  <p className="text-xs font-semibold uppercase text-muted-foreground">{fact.field_key || fact.field_path || "Resume fact"}</p>
                  <p className="mt-1 text-sm text-foreground">{String(fact.value ?? fact.source_text ?? "Unknown")}</p>
                  <Input className="mt-3 h-8" value={corrections[fact.fact_id] || ""} onChange={(event) => setCorrections((prev) => ({ ...prev, [fact.fact_id]: event.target.value }))} placeholder="Correct value (optional)" />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => void decideFact(fact, "confirm")}>Confirm</Button>
                    <Button size="sm" variant="outline" disabled={!corrections[fact.fact_id]?.trim()} onClick={() => void decideFact(fact, "correct")}>Correct</Button>
                    <Button size="sm" variant="ghost" onClick={() => void decideFact(fact, "reject")}>Reject</Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="dashboard-card">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-foreground">Saved roles and job descriptions</h3>
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowJobForm((value) => !value)}><Plus className="h-3.5 w-3.5" /> Add</Button>
        </div>
        {showJobForm && (
          <div className="mt-4 space-y-3 rounded-lg border border-border/60 bg-secondary/15 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input value={jobDraft.role} onChange={(event) => setJobDraft({ ...jobDraft, role: event.target.value })} placeholder="Role title" />
              <Input value={jobDraft.company} onChange={(event) => setJobDraft({ ...jobDraft, company: event.target.value })} placeholder="Company" />
              <Input value={jobDraft.experience_level} onChange={(event) => setJobDraft({ ...jobDraft, experience_level: event.target.value })} placeholder="Experience level" />
              <Input value={jobDraft.tech_stack} onChange={(event) => setJobDraft({ ...jobDraft, tech_stack: event.target.value })} placeholder="Tech stack, comma separated" />
            </div>
            <Textarea value={jobDraft.job_description} onChange={(event) => setJobDraft({ ...jobDraft, job_description: event.target.value })} placeholder="Paste the full job description" className="min-h-32" />
            <Button disabled={busyId === "new-job" || !jobDraft.role.trim() || !jobDraft.job_description.trim()} onClick={() => void createTarget()}>
              {busyId === "new-job" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target className="h-4 w-4" />} Save target
            </Button>
          </div>
        )}
        <div className="mt-4 space-y-2">
          {jobs.map((job) => (
            <div key={job.profile_id} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-secondary/20 p-3">
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => void selectJobProfile(job.profile_id).then(load)}>
                <p className="truncate text-sm font-semibold text-foreground">{job.role}{job.company ? ` at ${job.company}` : ""}</p>
                <p className="mt-1 text-xs text-muted-foreground">{job.experience_level || "Experience not set"} · {job.job_description ? "JD saved" : "JD missing"}</p>
              </button>
              {job.is_selected && <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">Selected</span>}
              <Button variant="ghost" size="icon-sm" disabled={busyId === job.profile_id} onClick={() => void removeTarget(job.profile_id)} aria-label="Delete job target"><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!jobs.length && !loading && (
            <div className="rounded-lg border border-dashed border-border/70 p-5 text-center">
              <FileText className="mx-auto h-5 w-5 text-muted-foreground" />
              <p className="mt-2 text-sm text-muted-foreground">No saved job target yet.</p>
            </div>
          )}
        </div>
        {error && <p className="mt-4 text-xs text-destructive">{error}</p>}
      </section>
    </div>
  )
}
