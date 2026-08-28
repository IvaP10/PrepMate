const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api"

function runtimeApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    const desktop = (window as Window & {
      prepmateDesktop?: { apiBaseUrl?: string }
    }).prepmateDesktop
    if (desktop?.apiBaseUrl) return `${desktop.apiBaseUrl.replace(/\/$/, "")}/api`
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL || process.env.PREPMATE_API_BASE_URL || DEFAULT_API_BASE_URL
}

export const API_CONFIG = {
  get BASE_URL() {
    return runtimeApiBaseUrl()
  },
  TIMEOUT: 30000,
  RETRY_ATTEMPTS: 1,
} as const

export const RESUME_MAX_FILE_BYTES = 4 * 1024 * 1024

export const API_ENDPOINTS = {
  RESUME: {
    UPLOAD: "/pre-interview/upload-resume",
    JOB: (jobId: string) => `/pre-interview/resume-jobs/${encodeURIComponent(jobId)}`,
    VERSIONS: "/pre-interview/resumes",
    CONFIRM: "/pre-interview/confirm-profile",
    FORM: "/pre-interview/form",
  },
  INTERVIEW: {
    START: "/interview/start",
    BLUEPRINTS: "/interview/blueprints",
    REPORT: "/interview/report",
    STATUS: "/interview/status",
    ANALYSIS_STATUS: "/interview",
    CANCEL: "/interview/cancel",
  },
  ANALYSIS: {
    RECONCILE_PERFORMANCE: "/analysis/reconcile-performance",
  },
  WORKSPACE: {
    INTERVIEW_PROFILE: "/workspace/interview-profile",
    JOB_PROFILES: "/workspace/job-profiles",
    RECENT_ACTIVITY: "/workspace/recent-activity",
    PERFORMANCE: "/workspace/performance",
    TECHNICAL_ROUNDS: "/workspace/technical-rounds",
    LEARNING: "/workspace/learning",
    EXERCISE_ATTEMPT: "/workspace/exercises",
    EXERCISE_RUN: "/workspace/exercises",
  },
} as const
