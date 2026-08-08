"use client"

import { useEffect, useMemo, useState } from "react"
import { Check, FileText, Loader2, Pencil, Plus, Play, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  createJobProfile,
  createInterviewBlueprint,
  deleteJobProfile,
  fetchInterviewProfile,
  fetchFlowPreflight,
  fetchJobProfiles,
  fetchResumeVersions,
  persistBrowserPreflight,
  selectJobProfile,
  updateJobProfile,
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
  requestTechnicalFullscreen,
  requestTechnicalMedia,
  requestTechnicalScreenShare,
} from "@/lib/technical-permissions"
import { requiresSavedJobProfile } from "@/lib/interview-setup-policy"
import { rememberRecoveryGraceSeconds } from "@/lib/session-integrity"

type SetupMode = "interview" | "technical"
type CompileStage = "idle" | "fullscreen" | "readiness" | "camera" | "screen" | "blueprint" | "preflight" | "starting"

const compileStageLabels: Record<Exclude<CompileStage, "idle">, string> = {
  fullscreen: "Opening full screen...",
  readiness: "Checking service readiness...",
  camera: "Checking camera and microphone...",
  screen: "Waiting for full-screen sharing...",
  blueprint: "Building your interview...",
  preflight: "Verifying setup...",
  starting: "Starting your round...",
}

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
    interview: "Google, Microsoft, NVIDIA, Amazon, Adobe.",
    technical: "Google, Microsoft, NVIDIA, Amazon, Adobe.",
  },
  {
    value: "mid_tier",
    label: "Mid Tier",
    interview: "Oracle, Cisco, Dell, SAP, Qualcomm.",
    technical: "Oracle, Cisco, Dell, SAP, Qualcomm.",
  },
  {
    value: "startup",
    label: "Startup",
    interview: "Early-stage startups and fast-moving product teams.",
    technical: "Early-stage startups and fast-moving product teams.",
  },
  {
    value: "custom",
    label: "Custom",
    interview: "Match a saved role and its full job description.",
    technical: "Match a saved role and its full job description.",
  },
]

export function InterviewSetupWizard({
  mode,
  onReady,
  onProfilesChanged,
  disabled,
}: {
  mode: SetupMode
  onReady: (blueprint: InterviewBlueprint, runtime: BlueprintRuntimeChoice, preflightId: string) => void
  onProfilesChanged?: () => void
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
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [editingProfileId, setEditingProfileId] = useState<number | null>(null)
  const [profileType, setProfileType] = useState<InterviewProfileType>("mid_tier")
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingTarget, setSavingTarget] = useState(false)
  const [deletingProfileId, setDeletingProfileId] = useState<number | null>(null)
  const [deleteCandidate, setDeleteCandidate] = useState<JobProfile | null>(null)
  const [profileError, setProfileError] = useState("")
  const interviewMode = "mock" as const
  const [compiling, setCompiling] = useState(false)
  const [compileError, setCompileError] = useState("")
  const [compileStage, setCompileStage] = useState<CompileStage>("idle")
  const [serviceReadiness, setServiceReadiness] = useState<"checking" | "ready" | "blocked">("checking")
  const [serviceReadinessMessage, setServiceReadinessMessage] = useState("")
  const [readinessRetry, setReadinessRetry] = useState(0)
  const [readinessFeedbackVisible, setReadinessFeedbackVisible] = useState(false)

  useEffect(() => {
    let cancelled = false
    const flow = technical ? "technical" : "interview"
    const checkReadiness = async () => {
      if (cancelled) return
      setServiceReadiness("checking")
      setServiceReadinessMessage("")
      try {
        const readiness = await fetchFlowPreflight(flow, { force: readinessRetry > 0 })
        if (cancelled) return
        setServiceReadiness(readiness.ready ? "ready" : "blocked")
        setServiceReadinessMessage(readiness.ready ? "" : readiness.message)
        if (readiness.ready) {
          rememberRecoveryGraceSeconds(readiness.recovery_grace_seconds)
        }
      } catch (error: any) {
        if (cancelled) return
        setServiceReadiness("blocked")
        setServiceReadinessMessage(error?.message || "Service readiness could not be checked.")
      }
    }
    void checkReadiness()
    return () => {
      cancelled = true
    }
  }, [readinessRetry, technical])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoadingAssets(true)
      const profilePromise = fetchInterviewProfile()
      const [resumeResult, jobResult] = await Promise.allSettled([
        fetchResumeVersions(),
        fetchJobProfiles(),
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
      const failed = [resumeResult, jobResult].filter((result) => result.status === "rejected") as PromiseRejectedResult[]
      if (failed.length) setAssetError(failed.map((result) => result.reason?.message || "Failed to load setup assets").join(" "))
      setLoadingAssets(false)
      void profilePromise.then((profile) => {
        if (cancelled) return
        setProfileType(profile.profile_type)
        if (profile.profile_type !== "custom") {
          setJobProfileId("")
          setRole("")
          setCompany("")
          setJobDescription("")
        }
      }).catch(() => undefined)
    })()
    return () => { cancelled = true }
  }, [technical])

  const selectedJob = useMemo(() => jobs.find((item) => String(item.profile_id) === jobProfileId), [jobProfileId, jobs])

  useEffect(() => {
    if (!selectedJob) return
    setRole(selectedJob.role || "")
    setCompany(selectedJob.company || "")
    setJobDescription(selectedJob.job_description || "")
  }, [selectedJob])

  const selectProfile = async (nextProfile: InterviewProfileType) => {
    if (savingProfile || deletingProfileId !== null) return
    if (nextProfile === profileType) {
      if (nextProfile === "custom" && jobs.length === 0) setShowProfileForm(true)
      return
    }
    const previousProfile = profileType
    setProfileType(nextProfile)
    if (nextProfile !== "custom") {
      setJobProfileId("")
      setRole("")
      setCompany("")
      setJobDescription("")
    }
    setShowProfileForm(nextProfile === "custom" && jobs.length === 0)
    setProfileError("")
    setSavingProfile(true)
    try {
      await updateInterviewProfile(nextProfile)
    } catch (error: any) {
      setProfileType(previousProfile)
      setProfileError(error?.message || "We could not save this selection. Please try again.")
    } finally {
      setSavingProfile(false)
    }
  }

  const selectSavedTarget = async (job: JobProfile) => {
    if (savingProfile || deletingProfileId !== null) return
    const previousJobProfileId = jobProfileId
    setJobProfileId(String(job.profile_id))
    setRole(job.role || "")
    setCompany(job.company || "")
    setJobDescription(job.job_description || "")
    setShowProfileForm(false)
    setProfileError("")
    setSavingProfile(true)
    try {
      await selectJobProfile(job.profile_id)
      setJobs((current) => current.map((item) => ({ ...item, is_selected: item.profile_id === job.profile_id })))
    } catch (error: any) {
      setJobProfileId(previousJobProfileId)
      setProfileError(error?.message || "We could not select this profile. Please try again.")
    } finally {
      setSavingProfile(false)
    }
  }

  const startNewCustomTarget = () => {
    setEditingProfileId(null)
    setJobProfileId("")
    setRole("")
    setCompany("")
    setJobDescription("")
    setShowProfileForm(true)
  }

  const cancelNewCustomTarget = () => {
    setEditingProfileId(null)
    setShowProfileForm(false)
    setRole(selectedJob?.role || "")
    setCompany(selectedJob?.company || "")
    setJobDescription(selectedJob?.job_description || "")
  }

  const saveCustomTarget = async () => {
    if (!role.trim() || !company.trim() || !jobDescription.trim() || savingTarget) return
    setSavingTarget(true)
    setProfileError("")
    try {
      const payload = {
        role: role.trim(),
        company: company.trim(),
        job_description: jobDescription.trim(),
      }
      const saved = editingProfileId !== null
        ? await updateJobProfile(editingProfileId, payload)
        : await createJobProfile(payload)
      await selectJobProfile(saved.profile_id)
      setJobs((current) => {
        const next = current.map((item) => ({ ...item, is_selected: false }))
        const selectedProfile = { ...saved, is_selected: true }
        const existingIndex = next.findIndex((item) => item.profile_id === saved.profile_id)
        if (existingIndex === -1) return [...next, selectedProfile]
        next[existingIndex] = selectedProfile
        return next
      })
      setJobProfileId(String(saved.profile_id))
      setRole(saved.role || "")
      setCompany(saved.company || "")
      setJobDescription(saved.job_description || "")
      setShowProfileForm(false)
      setEditingProfileId(null)
      onProfilesChanged?.()
    } catch (error: any) {
      setProfileError(error?.message || "We could not save this profile. Please try again.")
    } finally {
      setSavingTarget(false)
    }
  }

  const removeSavedTarget = async (job: JobProfile) => {
    if (savingProfile || deletingProfileId !== null) return
    const deletingSelectedTarget = String(job.profile_id) === jobProfileId
    setDeletingProfileId(job.profile_id)
    setProfileError("")
    try {
      await deleteJobProfile(job.profile_id)
      const remainingJobs = jobs.filter((item) => item.profile_id !== job.profile_id)
      setJobs(remainingJobs)
      if (deletingSelectedTarget) {
        const next = remainingJobs[0]
        if (next) {
          await selectJobProfile(next.profile_id)
          setJobs(remainingJobs.map((item) => ({ ...item, is_selected: item.profile_id === next.profile_id })))
          setJobProfileId(String(next.profile_id))
          setRole(next.role || "")
          setCompany(next.company || "")
          setJobDescription(next.job_description || "")
        } else {
          setJobProfileId("")
          setRole("")
          setCompany("")
          setJobDescription("")
        }
      }
      onProfilesChanged?.()
    } catch (error: any) {
      setProfileError(error?.message || "We could not delete this custom profile. Please try again.")
    } finally {
      setDeletingProfileId(null)
      setDeleteCandidate(null)
    }
  }

  const compile = async () => {
    if (!resumeId) return
    setCompiling(true)
    setCompileError("")
    try {
      const compiledJobProfileId = jobProfileId ? Number(jobProfileId) : null
      if (requiresSavedJobProfile(profileType) && !compiledJobProfileId) {
        throw new Error("Add or select a saved profile before starting this round.")
      }
      if (!navigator.onLine) {
        throw new Error(`A network connection is required before the ${technical ? "Technical Round" : "Interview Round"} can start.`)
      }
      const flow = technical ? "technical" : "interview"
      const fullscreenRequest = technical ? requestTechnicalFullscreen() : null
      setReadinessFeedbackVisible(true)
      if (technical) {
        setCompileStage("fullscreen")
        const fullscreen = await fullscreenRequest
        if (!fullscreen?.ok) throw new Error(fullscreen?.message || "Fullscreen is required before the technical round can start.")
      }
      setCompileStage("readiness")
      const readiness = await fetchFlowPreflight(flow, { force: serviceReadiness === "blocked" })
      setServiceReadiness(readiness.ready ? "ready" : "blocked")
      setServiceReadinessMessage(readiness.ready ? "" : readiness.message)
      if (!readiness.ready) throw new Error(readiness.message)
      rememberRecoveryGraceSeconds(readiness.recovery_grace_seconds)
      if (technical) {
        setCompileStage("screen")
        const screen = await requestTechnicalScreenShare()
        if (!screen.ok) throw new Error(screen.message)
      }
      setCompileStage("camera")
      const media = await requestTechnicalMedia()
      if (!media.ok) throw new Error(media.message)

      setCompileStage("blueprint")
      const payload: InterviewBlueprintRequest = {
        resume_id: resumeId,
        job_profile_id: profileType === "custom" ? compiledJobProfileId : null,
        interview_mode: interviewMode,
        interview_type: technical ? "technical" : "behavioral",
        profile_type: profileType,
      }
      const next = await createInterviewBlueprint(payload, newKey())
      if (!next.blueprint_id) throw new Error("We could not prepare your interview. Please try again.")
      setCompileStage("preflight")
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
      setCompileStage("starting")
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
      setCompileStage("idle")
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
                      className={`min-h-20 rounded-xl border p-3 text-left ${selected ? "border-primary bg-primary/10" : "border-border bg-background hover:border-primary/50"}`}
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
                  </div>
                  {!showProfileForm && (
                    <Button type="button" variant="outline" size="sm" disabled={savingProfile || deletingProfileId !== null} onClick={startNewCustomTarget}>
                      <Plus className="h-3.5 w-3.5" /> Add another
                    </Button>
                  )}
                </div>

                {!showProfileForm && jobs.length > 0 && (
                  <div className="grid gap-2 md:grid-cols-2">
                    {jobs.map((job) => {
                      const selected = String(job.profile_id) === jobProfileId
                      return (
                        <div
                          key={job.profile_id}
                          className={`flex w-full min-w-0 items-start rounded-lg border transition-colors ${selected ? "border-primary bg-primary/10" : "border-border bg-background hover:border-primary/50"}`}
                        >
                          <button
                            type="button"
                            disabled={savingProfile || deletingProfileId !== null}
                            onClick={() => void selectSavedTarget(job)}
                            className="min-w-0 flex-1 p-3 text-left disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-semibold text-foreground">{job.role}{job.company ? ` at ${job.company}` : ""}</span>
                              <span className="mt-1 block truncate text-xs leading-5 text-muted-foreground">{job.job_description ? "Full job description saved" : "No job description saved"}</span>
                            </span>
                          </button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="m-2 h-8 shrink-0 px-2 text-xs text-muted-foreground hover:text-foreground"
                            disabled={savingProfile || deletingProfileId !== null}
                            onClick={() => {
                              setEditingProfileId(job.profile_id)
                              setRole(job.role || "")
                              setCompany(job.company || "")
                              setJobDescription(job.job_description || "")
                              setProfileError("")
                              setShowProfileForm(true)
                            }}
                            aria-label={`Edit ${job.role} job target`}
                          >
                            <Pencil className="h-3.5 w-3.5" /> Edit
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            className="m-2 text-muted-foreground hover:text-destructive"
                            disabled={savingProfile || deletingProfileId !== null}
                            onClick={() => setDeleteCandidate(job)}
                            aria-label={`Delete ${job.role} job target`}
                          >
                            {deletingProfileId === job.profile_id
                              ? <Loader2 className="h-4 w-4 animate-spin" />
                              : <Trash2 className="h-4 w-4" />}
                          </Button>
                        </div>
                      )
                    })}
                  </div>
                )}

                {!jobs.length && !showProfileForm && (
                  <p className="rounded-lg border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">No saved role yet. Add the role and full job description here.</p>
                )}

                {showProfileForm && (
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="md:col-span-2">
                      <p className="text-sm font-semibold text-foreground">{editingProfileId !== null ? "Edit saved role" : "Add saved role"}</p>
                      <p className="mt-1 text-xs text-muted-foreground">View and edit the complete job description here.</p>
                    </div>
                    <Field label="Role title"><Input value={role} onChange={(event) => setRole(event.target.value)} placeholder="Backend Engineer" className="placeholder:text-muted-foreground/70" /></Field>
                    <Field label="Company"><Input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="Company name" className="placeholder:text-muted-foreground/70" /></Field>
                    <div className="md:col-span-2">
                      <Field label="Job description">
                        <Textarea value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="Paste the complete responsibilities, requirements, and preferred skills." className="min-h-56 placeholder:text-muted-foreground/70" />
                      </Field>
                    </div>
                    <div className="flex justify-end gap-2 md:col-span-2">
                      <Button type="button" variant="ghost" disabled={savingTarget} onClick={cancelNewCustomTarget}>Cancel</Button>
                      <Button type="button" disabled={savingTarget || !role.trim() || !company.trim() || !jobDescription.trim()} onClick={() => void saveCustomTarget()}>
                        {savingTarget ? <Loader2 className="h-4 w-4 animate-spin" /> : <SaveIcon />} {editingProfileId !== null ? "Save changes" : "Save job target"}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

        </>
      )}
      {(assetError || compileError || profileError || (readinessFeedbackVisible && serviceReadiness === "blocked")) && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <span>{compileError || profileError || (readinessFeedbackVisible && serviceReadiness === "blocked" ? serviceReadinessMessage : "") || assetError}</span>
          {readinessFeedbackVisible && serviceReadiness === "blocked" && (
            <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={() => {
              setCompileError("")
              setReadinessRetry((attempt) => attempt + 1)
            }}>
              Retry
            </Button>
          )}
        </div>
      )}
      {readinessFeedbackVisible && serviceReadiness === "checking" && !compiling && (
        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-secondary/20 px-3 py-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking service readiness...
        </div>
      )}
      {!loadingAssets && !resumes.length && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"><FileText className="mr-2 inline h-4 w-4" />Upload and activate a resume before starting.</div>}
      <div className="flex justify-end border-t border-border/60 pt-4">
        <Button disabled={disabled || compiling || savingProfile || savingTarget || deletingProfileId !== null || showProfileForm || !resumeId || (requiresSavedJobProfile(profileType) && !jobProfileId)} onClick={() => void compile()}>
          {compiling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {compiling && compileStage !== "idle" ? compileStageLabels[compileStage] : `Start ${technical ? "Technical Round" : "Interview Round"}`}
        </Button>
      </div>
      <Dialog open={Boolean(deleteCandidate)} onOpenChange={(open) => { if (!open && deletingProfileId === null) setDeleteCandidate(null) }}>
        <DialogContent showCloseButton={deletingProfileId === null}>
          <DialogHeader>
            <DialogTitle>Delete job target?</DialogTitle>
            <DialogDescription>
              {deleteCandidate ? `${deleteCandidate.role}${deleteCandidate.company ? ` at ${deleteCandidate.company}` : ""} will be removed from saved job targets.` : "This job target will be removed."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" disabled={deletingProfileId !== null} onClick={() => setDeleteCandidate(null)}>Cancel</Button>
            <Button type="button" variant="destructive" disabled={!deleteCandidate || deletingProfileId !== null} onClick={() => deleteCandidate && void removeSavedTarget(deleteCandidate)}>
              {deletingProfileId !== null && <Loader2 className="h-4 w-4 animate-spin" />} Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SaveIcon() {
  return <Check className="h-4 w-4" />
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="space-y-1.5"><span className="text-sm font-medium text-foreground">{label}</span>{children}</label>
}
