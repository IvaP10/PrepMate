"use client"

import { useEffect, useMemo, useState } from "react"
import { BriefcaseBusiness, Check, FileText, Loader2, Plus, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  createJobProfile,
  createInterviewBlueprint,
  fetchInterviewProfile,
  fetchFlowPreflight,
  fetchJobProfiles,
  fetchResumeVersions,
  persistBrowserPreflight,
  selectJobProfile,
  updateInterviewProfile,
  type InterviewBlueprint,
  type InterviewBlueprintRequest,
  type InterviewProfileType,
  type JobProfile,
  type ResumeVersion,
} from "@/lib/api"
import {
  getTechnicalPermissionState,
  markPreflightCompleted,
  releaseTechnicalPermissions,
  requestTechnicalMedia,
  requestTechnicalScreenShare,
} from "@/lib/technical-permissions"
import { rememberRecoveryGraceSeconds } from "@/lib/session-integrity"

type SetupMode = "interview" | "technical"

export type BlueprintRuntimeChoice = {
  inputMode: "voice" | "text"
  cameraEnabled: boolean
  interviewMode: "mock"
}

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `blueprint-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const profileChoices: {
  value: InterviewProfileType
  label: string
  interview: string
  technical: string
}[] = [
  {
    value: "top_tier",
    label: "Top Tier",
    interview: "High bar and deep follow-ups.",
    technical: "Harder multi-step problems.",
  },
  {
    value: "mid_tier",
    label: "Mid Tier",
    interview: "Balanced execution and teamwork.",
    technical: "Practical engineering problems.",
  },
  {
    value: "startup",
    label: "Startup",
    interview: "Ownership, adaptability, and shipping.",
    technical: "Fast, practical problem solving.",
  },
  {
    value: "custom",
    label: "Custom",
    interview: "Use a saved role and full job description.",
    technical: "Use a saved role and full job description.",
  },
]

export function InterviewSetupWizard({
  mode,
  onReady,
  disabled,
}: {
  mode: SetupMode
  onReady: (blueprint: InterviewBlueprint, runtime: BlueprintRuntimeChoice, preflightId: string) => void
  disabled?: boolean
}) {
  const technical = mode === "technical"
  const [resumes, setResumes] = useState<ResumeVersion[]>([])
  const [jobs, setJobs] = useState<JobProfile[]>([])
  const [loadingAssets, setLoadingAssets] = useState(true)
  const [assetError, setAssetError] = useState("")
  const [resumeId, setResumeId] = useState("")
  const [jobProfileId, setJobProfileId] = useState("")
  const [role, setRole] = useState("")
  const [company, setCompany] = useState("")
  const [jobDescription, setJobDescription] = useState("")
  const [showCustomForm, setShowCustomForm] = useState(false)
  const [profileType, setProfileType] = useState<InterviewProfileType>("mid_tier")
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileError, setProfileError] = useState("")
  const interviewMode = "mock" as const
  const [compiling, setCompiling] = useState(false)
  const [compileError, setCompileError] = useState("")

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoadingAssets(true)
      const [resumeResult, jobResult, profileResult] = await Promise.allSettled([
        fetchResumeVersions(),
        fetchJobProfiles(),
        fetchInterviewProfile(),
      ])
      if (cancelled) return
      if (resumeResult.status === "fulfilled") {
        setResumes(resumeResult.value.resumes)
        setResumeId(resumeResult.value.active_resume_id || resumeResult.value.resumes[0]?.resume_id || "")
      }
      if (jobResult.status === "fulfilled") {
        setJobs(jobResult.value)
        const selected = jobResult.value.find((item) => item.is_selected) || jobResult.value[0]
        if (selected) {
          setJobProfileId(String(selected.profile_id))
          setRole(selected.role || "")
          setCompany(selected.company || "")
          setJobDescription(selected.job_description || "")
        }
      }
      if (profileResult.status === "fulfilled") setProfileType(profileResult.value.profile_type)
      const failed = [resumeResult, jobResult].filter((result) => result.status === "rejected") as PromiseRejectedResult[]
      if (failed.length) setAssetError(failed.map((result) => result.reason?.message || "Failed to load setup assets").join(" "))
      setLoadingAssets(false)
    })()
    return () => { cancelled = true }
  }, [])

  const selectedJob = useMemo(() => jobs.find((item) => String(item.profile_id) === jobProfileId), [jobProfileId, jobs])

  useEffect(() => {
    if (!selectedJob) return
    setRole(selectedJob.role || "")
    setCompany(selectedJob.company || "")
    setJobDescription(selectedJob.job_description || "")
  }, [selectedJob])

  const selectProfile = async (nextProfile: InterviewProfileType) => {
    if (nextProfile === profileType || savingProfile) return
    const previousProfile = profileType
    setProfileType(nextProfile)
    setShowCustomForm(nextProfile === "custom" && jobs.length === 0)
    setProfileError("")
    setSavingProfile(true)
    try {
      await updateInterviewProfile(nextProfile)
    } catch (error: any) {
      setProfileType(previousProfile)
      setProfileError(error?.message || "We could not save your company environment. Please try again.")
    } finally {
      setSavingProfile(false)
    }
  }

  const selectSavedTarget = async (job: JobProfile) => {
    const previousProfile = profileType
    setProfileType("custom")
    setJobProfileId(String(job.profile_id))
    setRole(job.role || "")
    setCompany(job.company || "")
    setJobDescription(job.job_description || "")
    setShowCustomForm(false)
    setProfileError("")
    setSavingProfile(true)
    try {
      await Promise.all([
        previousProfile === "custom" ? Promise.resolve() : updateInterviewProfile("custom"),
        selectJobProfile(job.profile_id),
      ])
    } catch (error: any) {
      setProfileType(previousProfile)
      setProfileError(error?.message || "We could not select this company environment. Please try again.")
    } finally {
      setSavingProfile(false)
    }
  }

  const startNewCustomTarget = () => {
    setJobProfileId("")
    setRole("")
    setCompany("")
    setJobDescription("")
    setShowCustomForm(true)
  }

  const compile = async () => {
    if (!resumeId) return
    setCompiling(true)
    setCompileError("")
    try {
      let compiledJobProfileId = jobProfileId ? Number(jobProfileId) : null
      if (profileType === "custom") {
        if (!role.trim() || !jobDescription.trim()) {
          throw new Error("Custom requires the role and full job description.")
        }
      } else if (!compiledJobProfileId) {
        throw new Error("Add a role and full job description under Custom before starting this round.")
      }
      if (!compiledJobProfileId) {
        // A new Custom target is saved after browser permissions are granted.
        if (profileType !== "custom") throw new Error("A job target is required to prepare this interview.")
      }
      if (!navigator.onLine) {
        throw new Error(`A network connection is required before the ${technical ? "Technical" : "Interview"} Round can start.`)
      }

      // Start every browser-native permission request in the original Start
      // button gesture. There is deliberately no custom permission screen in
      // between: the browser prompts, then the round starts automatically.
      const flow = technical ? "technical" : "interview"
      const readinessPromise = fetchFlowPreflight(flow)
      const mediaPromise = requestTechnicalMedia()
      const screenPromise = requestTechnicalScreenShare()
      const [readiness, media, screen] = await Promise.all([
        readinessPromise,
        mediaPromise,
        screenPromise,
      ])
      if (!readiness.ready) throw new Error(readiness.message)
      if (!media.ok) throw new Error(media.message)
      if (!screen.ok) throw new Error(screen.message)
      rememberRecoveryGraceSeconds(readiness.recovery_grace_seconds)

      if (profileType === "custom") {
        const matchesSelectedTarget = Boolean(
          selectedJob
          && selectedJob.role.trim() === role.trim()
          && (selectedJob.company || "").trim() === company.trim()
          && (selectedJob.job_description || "").trim() === jobDescription.trim()
        )
        if (!matchesSelectedTarget) {
          const created = await createJobProfile({
            role: role.trim(),
            company: company.trim(),
            job_description: jobDescription.trim(),
          })
          await selectJobProfile(created.profile_id)
          compiledJobProfileId = created.profile_id
          setJobs((current) => [...current.map((item) => ({ ...item, is_selected: false })), { ...created, is_selected: true }])
          setJobProfileId(String(created.profile_id))
        }
      }
      if (!compiledJobProfileId) throw new Error("A job target is required to prepare this interview.")
      const payload: InterviewBlueprintRequest = {
        resume_id: resumeId,
        job_profile_id: compiledJobProfileId,
        interview_mode: interviewMode,
        interview_type: technical ? "technical" : "behavioral",
        profile_type: profileType,
      }
      const next = await createInterviewBlueprint(payload, newKey())
      if (!next.blueprint_id) throw new Error("We could not prepare your interview. Please try again.")
      const permissionState = getTechnicalPermissionState()
      const persisted = await persistBrowserPreflight({
        blueprint_id: next.blueprint_id,
        flow,
        camera_ready: permissionState.cameraReady,
        microphone_ready: permissionState.microphoneReady,
        microphone_level_detected: permissionState.microphoneReady,
        screen_share_ready: permissionState.screenShareReady,
        network_ready: navigator.onLine,
      })
      markPreflightCompleted()
      onReady(next, {
        inputMode: technical ? "text" : "voice",
        cameraEnabled: true,
        interviewMode,
      }, persisted.preflight_id)
    } catch (err: any) {
      await releaseTechnicalPermissions()
      setCompileError(err?.message || "We could not prepare your interview. Please try again.")
    } finally {
      setCompiling(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold text-foreground">
          {technical ? "Technical Round" : "Interview Round"}
        </h3>
      </div>
      {loadingAssets ? (
        <div className="flex min-h-36 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-primary" /></div>
      ) : (
        <>
          <div className="space-y-4">
            <div className="space-y-2">
              <div>
                <p className="text-sm font-medium text-foreground">Company environment</p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" role="radiogroup" aria-label={`${technical ? "Technical" : "Interview"} profile`}>
                {profileChoices.map((profile) => {
                  const selected = profileType === profile.value
                  return (
                    <button
                      key={`${profile.value}-${selected ? "selected" : "idle"}`}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={savingProfile}
                      onClick={() => void selectProfile(profile.value)}
                      className={`min-h-24 rounded-xl border p-3 text-left ${selected ? "border-primary bg-primary/10" : "border-border bg-background hover:border-primary/50"}`}
                    >
                      <span className={`text-sm font-semibold ${selected ? "text-primary" : "text-foreground"}`}>{profile.label}</span>
                      <span className="mt-1 block text-xs leading-4 text-muted-foreground">{technical ? profile.technical : profile.interview}</span>
                      {profile.value === "custom" && selectedJob && (
                        <span className="mt-2 block truncate text-xs font-semibold text-foreground">{selectedJob.role}{selectedJob.company ? ` at ${selectedJob.company}` : ""}</span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>

            {profileType === "custom" && (
              <div className="space-y-3 rounded-xl border border-border/60 bg-secondary/10 p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-foreground">Saved roles and full job descriptions</p>
                    <p className="mt-1 text-xs text-muted-foreground">Choose the company-specific environment for this round.</p>
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={startNewCustomTarget}>
                    <Plus className="h-3.5 w-3.5" /> Add another
                  </Button>
                </div>

                {jobs.length > 0 && (
                  <div className="grid gap-2 md:grid-cols-2">
                    {jobs.map((job) => {
                      const selected = !showCustomForm && String(job.profile_id) === jobProfileId
                      return (
                        <button
                          key={job.profile_id}
                          type="button"
                          disabled={savingProfile}
                          onClick={() => void selectSavedTarget(job)}
                          className={`rounded-lg border p-3 text-left transition-colors ${selected ? "border-primary bg-primary/10" : "border-border bg-background hover:border-primary/50"}`}
                        >
                          <span className="flex items-start justify-between gap-3">
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-semibold text-foreground">{job.role}{job.company ? ` at ${job.company}` : ""}</span>
                              <span className="mt-1 line-clamp-2 block text-xs leading-5 text-muted-foreground">{job.job_description || "No job description saved"}</span>
                            </span>
                            {selected ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> : <BriefcaseBusiness className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}

                {!jobs.length && !showCustomForm && (
                  <p className="rounded-lg border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">No saved role yet. Add the role and full job description here.</p>
                )}
              </div>
            )}
          </div>

          {profileType === "custom" && showCustomForm && (
            <div className="grid gap-4 border-t border-border pt-4 md:grid-cols-2">
              <Field label="Role"><Input value={role} onChange={(event) => setRole(event.target.value)} placeholder="Backend Engineer" /></Field>
              <Field label="Company name (optional)"><Input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="Company name" /></Field>
              <div className="md:col-span-2">
                <Field label="Full job description">
                  <Textarea value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="Paste the complete responsibilities, requirements, and preferred skills." className="min-h-28" />
                </Field>
              </div>
            </div>
          )}

          {!technical && <p className="text-xs text-muted-foreground">Voice · camera required</p>}
        </>
      )}
      {(assetError || compileError || profileError) && <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{compileError || profileError || assetError}</div>}
      {!loadingAssets && !resumes.length && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"><FileText className="mr-2 inline h-4 w-4" />Upload and activate a resume before starting.</div>}
      <div className="flex justify-end border-t border-border/60 pt-4">
        <Button disabled={disabled || compiling || savingProfile || !resumeId || (profileType === "custom" ? (!role.trim() || !jobDescription.trim()) : !jobProfileId)} onClick={() => void compile()}>
          {compiling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {compiling ? "Preparing..." : `Start ${technical ? "Technical Round" : "Interview Round"}`}
        </Button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="space-y-1.5"><span className="text-sm font-medium text-foreground">{label}</span>{children}</label>
}
