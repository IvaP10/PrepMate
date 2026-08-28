import { API_CONFIG, API_ENDPOINTS } from './config'
import type {
  ResumeData,
  UploadResponse,
  SubmitResponse,
  ApiError,
} from '@/types/resume'

function friendlyMessage(raw: string): string {
  const lower = raw.toLowerCase()
  if (lower.includes('forbidden') || lower.includes('403')) return 'The local request was not allowed.'
  if (lower.includes('unauthorized') || lower.includes('401')) return 'The local service rejected this request.'
  if (lower.includes('not found') || lower.includes('404')) return 'The requested resource was not found.'
  if (lower.includes('429') || lower.includes('too many')) return 'Too many requests. Please wait a moment.'
  if (lower.includes('500') || lower.includes('internal server')) return 'Something went wrong. Please try again.'
  if (lower.includes('network') || lower.includes('failed to fetch') || lower.includes('abort')) return 'Connection issue. Check your network and try again.'
  if (lower.startsWith('http ')) return 'Something went wrong. Please try again.'
  return raw
}

function requestCanRetry(options: RequestInit): boolean {
  const method = String(options.method || 'GET').toUpperCase()
  if (['GET', 'HEAD', 'OPTIONS'].includes(method)) return true
  try {
    const headers = new Headers(options.headers)
    return headers.has('Idempotency-Key') || headers.has('X-Idempotency-Key')
  } catch {
    return false
  }
}

async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  retries: number = API_CONFIG.RETRY_ATTEMPTS
): Promise<Response> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  const canRetry = requestCanRetry(options)
  try {
    const controller = new AbortController()
    timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT)

    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    })

    clearTimeout(timeoutId)

    if (response.ok) {
      return response
    }

    if ((response.status >= 500 || response.status === 429) && retries > 0 && canRetry) {
      const retryAfter = Number(response.headers.get('Retry-After'))
      const delay = Number.isFinite(retryAfter) && retryAfter > 0
        ? retryAfter * 1000
        : 750 + ((API_CONFIG.RETRY_ATTEMPTS - retries) * 500)
      await new Promise(resolve => setTimeout(resolve, delay))
      return fetchWithRetry(url, options, retries - 1)
    }

    const body = await response.json().catch(() => null)
    const detail = body?.detail || body?.message || ''
    throw new Error(friendlyMessage(detail || `HTTP ${response.status}: ${response.statusText}`))
  } catch (error) {
    if (timeoutId) clearTimeout(timeoutId)
    const retryable = error instanceof DOMException && error.name === 'AbortError'
      || error instanceof TypeError
      || (error instanceof Error && /network|failed to fetch|abort/i.test(error.message))
    if (retries > 0 && retryable && canRetry) {
      await new Promise(resolve => setTimeout(resolve, 750 + ((API_CONFIG.RETRY_ATTEMPTS - retries) * 500)))
      return fetchWithRetry(url, options, retries - 1)
    }
    if (error instanceof Error) {
      throw new Error(friendlyMessage(error.message))
    }
    throw new Error('Something went wrong. Please try again.')
  }
}

export type FlowPreflightStatus = {
  flow: 'interview' | 'technical'
  input_mode?: 'voice' | 'text'
  ready: boolean
  status: 'ready' | 'not_ready' | string
  message: string
  recovery_grace_seconds: number
  checks: Record<string, { healthy?: boolean; [key: string]: unknown }>
}

const FLOW_PREFLIGHT_CACHE_TTL_MS = 10_000
const flowPreflightCache = new Map<string, { value: FlowPreflightStatus; expiresAt: number }>()
const flowPreflightRequests = new Map<string, Promise<FlowPreflightStatus>>()

export async function fetchFlowPreflight(
  flow: 'interview' | 'technical',
  options: { force?: boolean; inputMode?: 'voice' | 'text' } = {},
): Promise<FlowPreflightStatus> {
  const inputMode = options.inputMode || 'text'
  const cacheKey = `${flow}:${inputMode}`
  const activeRequest = flowPreflightRequests.get(cacheKey)
  if (activeRequest) return activeRequest

  if (!options.force) {
    const cached = flowPreflightCache.get(cacheKey)
    if (cached && cached.expiresAt > Date.now()) return cached.value
  }

  const request = (async () => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT)
    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}/preflight?flow=${flow}&input_mode=${inputMode}`, {
        signal: controller.signal,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok && response.status !== 503) {
        throw new Error(friendlyMessage(payload?.detail || payload?.message || `HTTP ${response.status}`))
      }
      if (!payload || typeof payload.ready !== 'boolean') {
        throw new Error('The service readiness response was invalid.')
      }
      return payload as FlowPreflightStatus
    } catch (error) {
      if (error instanceof Error) throw new Error(friendlyMessage(error.message))
      throw new Error('Service readiness could not be checked.')
    } finally {
      clearTimeout(timeoutId)
    }
  })()

  flowPreflightRequests.set(cacheKey, request)
  try {
    const result = await request
    flowPreflightCache.set(cacheKey, { value: result, expiresAt: Date.now() + FLOW_PREFLIGHT_CACHE_TTL_MS })
    return result
  } finally {
    if (flowPreflightRequests.get(cacheKey) === request) flowPreflightRequests.delete(cacheKey)
  }
}

export type PersistedPreflight = FlowPreflightStatus & {
  preflight_id: string
  blueprint_id: string
  expires_at: string
}

export async function persistBrowserPreflight(payload: {
  blueprint_id: string
  flow: 'interview' | 'technical'
  input_mode: 'voice' | 'text'
  camera_ready: boolean
  microphone_ready: boolean
  microphone_level_detected: boolean
  screen_share_ready: boolean
  network_ready: boolean
  error_codes?: string[]
}): Promise<PersistedPreflight> {
  const response = await fetchWithRetry(`${API_CONFIG.BASE_URL}/preflight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function uploadResume(file: File): Promise<{ uploadResponse: UploadResponse; parsedData: ResumeData }> {
  const requestId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `resume-${Date.now()}`
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 45_000)
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.UPLOAD}`,
      {
        method: 'POST',
        headers: {
          'X-Request-ID': requestId,
        },
        body: formData,
        signal: controller.signal,
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const responseRequestId = response.headers.get('X-Request-ID') || body.request_id || requestId
      throw {
        code: body.error?.code || 'UPLOAD_FAILED',
        message: friendlyMessage(body.error?.message || body.detail || body.message || 'Upload failed'),
        details: {
          request_id: responseRequestId,
          retryable: Boolean(body.error?.retryable),
          status: response.status,
        },
      } as ApiError
    }

    let data = await response.json()
    if (response.status === 202 && data.job_id) {
      const deadline = Date.now() + 60_000
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 750))
        const statusResponse = await fetchWithRetry(
          `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.JOB(String(data.job_id))}`,
          { method: 'GET' },
        )
        const statusData = await statusResponse.json().catch(() => ({}))
        if (statusData.status === 'completed' || statusData.job?.status === 'completed') {
          data = statusData
          break
        }
        if (statusData.status === 'dead_letter' || statusData.job?.status === 'dead_letter') {
          throw {
            code: 'UPLOAD_FAILED',
            message: 'Resume processing failed. Please try the upload again.',
            details: { request_id: requestId, retryable: true },
          } as ApiError
        }
      }
      if (data.status !== 'completed' && data.job?.status !== 'completed') {
        throw {
          code: 'UPLOAD_TIMEOUT',
          message: 'Resume processing is still running. Please try again in a moment.',
          details: { request_id: requestId, retryable: true },
        } as ApiError
      }
    }

    const profile = data.extracted_profile || {}

    const storedResume = data.resume || {}
    const uploadResponse: UploadResponse = {
      success: true,
      fileId: String(storedResume.resume_id || data.resume_id || ''),
      fileName: storedResume.source_filename || file.name,
      uploadedAt: storedResume.created_at || new Date().toISOString(),
    }

    const parsedData: ResumeData = {
      fullName: profile.name || '',
      email: profile.email || '',
      phoneNumber: profile.phone || '',
      linkedinUrl: profile.linkedin || profile.links?.linkedin || '',
      githubUrl: profile.github || profile.links?.github || '',
      portfolioUrl: profile.portfolio || profile.links?.portfolio || '',
      targetRole: profile.target_role || '',
      professionalSummary: profile.summary || '',
      summary: profile.summary || '',
      skills: (profile.skills || []).map((s: string) => ({ name: s })),
      experiences: (profile.experience || []).map((exp: any) => {
        const parts = exp.duration?.split(' - ') || [];
        const end = parts.length > 1 ? parts[1].trim() : '';
        return {
          company: exp.company || '',
          position: exp.title || '',
          startDate: parts[0] || '',
          endDate: end,
          description: exp.description || '',
          isCurrent: end.toLowerCase().includes('present') || end.toLowerCase().includes('current'),
        };
      }),
      education: (profile.education || []).map((edu: any) => ({
        institution: edu.institution || '',
        degree: edu.degree || '',
        field: edu.field || '',
        endYear: edu.year ? parseInt(edu.year, 10) : undefined,
        gpa: edu.cgpa ? parseFloat(edu.cgpa) : undefined,
      })),
      projects: (profile.projects || []).map((proj: any) => ({
        name: proj.name || '',
        description: proj.description || '',
        technologies: proj.technologies || [],
      })),
      languages: (profile.languages || []).map((l: string) => ({ name: l, proficiency: 'professional' as const })),
      certifications: (profile.certifications || []).map((c: string) => ({ name: c, issuer: '' })),
      softSkills: profile.soft_skills || [],
      achievements: profile.achievements || [],
      interests: profile.interests || [],
      metadata: {
        resumeId: storedResume.resume_id || data.resume_id || undefined,
        versionNumber: storedResume.version_number || undefined,
        uploadedAt: new Date().toISOString(),
        parsedAt: new Date().toISOString(),
      },
    }

    return { uploadResponse, parsedData }
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && 'message' in error) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw {
        code: 'UPLOAD_TIMEOUT',
        message: 'Resume processing took too long. Try again with a text-based PDF or DOCX.',
        details: { request_id: requestId, retryable: true },
      } as ApiError
    }
    throw {
      code: 'UPLOAD_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to upload resume',
      details: { request_id: requestId, retryable: true },
    } as ApiError
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function submitResume(data: ResumeData, resumeId?: string): Promise<SubmitResponse> {
  try {
    const profile = {
      name: data.fullName,
      email: data.email || '',
      phone: data.phoneNumber || '',
      skills: data.skills.map(s => s.name),
      education: data.education.map(edu => ({
        degree: edu.degree,
        institution: edu.institution,
        year: edu.endYear?.toString() || '',
        field: edu.field || '',
      })),
      experience: data.experiences.map(exp => ({
        title: exp.position,
        company: exp.company,
        duration: [exp.startDate, exp.isCurrent ? 'Present' : exp.endDate].filter(Boolean).join(' - '),
        description: exp.description || '',
      })),
      projects: (data.projects || []).map(proj => ({
        name: proj.name,
        description: proj.description,
        technologies: proj.technologies || [],
      })),
      languages: data.languages?.map(l => l.name) || [],
      certifications: data.certifications?.map(c => c.name) || [],
      soft_skills: data.softSkills || [],
      achievements: data.achievements || [],
      interests: data.interests || [],
      linkedin: data.linkedinUrl || '',
      github: data.githubUrl || '',
      portfolio: data.portfolioUrl || '',
      summary: data.professionalSummary || '',
      target_role: data.targetRole || '',
    }

    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.CONFIRM}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ profile, resume_id: resumeId || data.metadata?.resumeId || null }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(body.detail || body.message || 'Submission failed'))
    }

    const result = await response.json()
    return {
      success: result.success,
      resumeId: result.resume_id || resumeId || data.metadata?.resumeId || '',
      message: result.message || 'Profile saved',
    }
  } catch (error) {
    throw {
      code: 'SUBMIT_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to submit resume',
    } as ApiError
  }
}

export async function getResume(): Promise<ResumeData> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.FORM}`,
      {
        method: 'GET',
      }
    )

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Resume not found')
      }
      throw new Error(`Fetch failed: ${response.statusText}`)
    }

    const data = await response.json()
    const form = data.form_data || {}
    const activeResume = data.resume || {}

    return {
      fullName: form.name || '',
      email: form.email || '',
      phoneNumber: form.phone || '',
      linkedinUrl: form.linkedin || '',
      githubUrl: form.github || '',
      portfolioUrl: form.portfolio || '',
      targetRole: form.target_role || '',
      professionalSummary: form.summary || '',
      skills: (form.skills || []).map((s: string) => ({ name: s })),
      experiences: (form.experience || []).map((exp: any) => {
        const parts = exp.duration?.split(' - ') || [];
        const end = parts.length > 1 ? parts[1].trim() : '';
        return {
          company: exp.company || '',
          position: exp.title || '',
          startDate: parts[0] || '',
          endDate: end,
          description: exp.description || '',
          isCurrent: end.toLowerCase().includes('present') || end.toLowerCase().includes('current'),
        };
      }),
      education: (form.education || []).map((edu: any) => ({
        institution: edu.institution || '',
        degree: edu.degree || '',
        field: edu.field || '',
        endYear: edu.year ? parseInt(edu.year) : undefined,
      })),
      projects: (form.projects || []).map((proj: any) => ({
        name: proj.name || '',
        description: proj.description || '',
        technologies: proj.technologies || [],
      })),
      languages: (form.languages || []).map((l: string) => ({ name: l, proficiency: 'professional' })),
      certifications: (form.certifications || []).map((c: string) => ({ name: c, issuer: '' })),
      softSkills: form.soft_skills || [],
      achievements: form.achievements || [],
      interests: form.interests || [],
      metadata: {
        resumeId: activeResume.resume_id || data.resume_id || undefined,
        versionNumber: activeResume.version_number || undefined,
        uploadedAt: activeResume.created_at || new Date().toISOString(),
        parsedAt: activeResume.updated_at || undefined,
      },
    }
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve resume',
    } as ApiError
  }
}

export interface ResumeFact {
  fact_id: string
  field_key?: string | null
  field_path?: string | null
  value?: unknown
  source_text?: string | null
  confidence?: number | null
  status?: 'pending' | 'confirmed' | 'corrected' | 'rejected' | string
}

export interface ResumeVersion {
  resume_id: string
  version_number: number
  is_active: boolean
  confirmation_status: string
  source_filename?: string | null
  parser_version?: string | null
  created_at?: string | null
  updated_at?: string | null
  derived_taxonomy?: Record<string, unknown>
  resume_payload?: Record<string, any>
  facts?: ResumeFact[]
  parent_resume_id?: string | null
  superseded_at?: string | null
  immutable?: boolean
  referenced?: boolean
}

export interface ResumeVersionsResponse {
  resumes: ResumeVersion[]
  active_resume_id: string | null
}

export async function fetchResumeVersions(): Promise<ResumeVersionsResponse> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.VERSIONS}`,
      { method: 'GET' },
    )
    const data = await response.json()
    const resumes = Array.isArray(data) ? data : Array.isArray(data.resumes) ? data.resumes : []
    return {
      resumes,
      active_resume_id: data.active_resume_id || resumes.find((item: ResumeVersion) => item.is_active)?.resume_id || null,
    }
  } catch (error) {
    throw {
      code: 'RESUME_VERSIONS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load resume versions',
    } as ApiError
  }
}

export async function activateResumeVersion(resumeId: string): Promise<ResumeVersion> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.VERSIONS}/${encodeURIComponent(resumeId)}/activate`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
      },
    )
    const data = await response.json()
    return data.resume || data
  } catch (error) {
    throw {
      code: 'RESUME_ACTIVATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to activate resume version',
    } as ApiError
  }
}

export async function deleteResumeVersion(resumeId: string): Promise<void> {
  try {
    await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.VERSIONS}/${encodeURIComponent(resumeId)}`,
      { method: 'DELETE' },
    )
  } catch (error) {
    throw {
      code: 'RESUME_DELETE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to delete resume version',
    } as ApiError
  }
}

export async function updateResumeFacts(resumeId: string, decisions: Array<{
  fact_id: string
  action: 'confirm' | 'correct' | 'reject'
  corrected_value?: unknown
}>): Promise<ResumeVersion> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.VERSIONS}/${encodeURIComponent(resumeId)}/facts`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions }),
      },
    )
    const data = await response.json()
    return data.resume || data
  } catch (error) {
    throw {
      code: 'RESUME_FACT_UPDATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to update resume facts',
    } as ApiError
  }
}

export interface ExactImproveTarget {
  mode?: 'interview' | 'mock' | 'technical' | string | null
  mission_id: string
  roadmap_node_id: string
  exercise_id: string
}

export interface ImproveNextAction {
  type: string
  label?: string | null
  title?: string | null
  description?: string | null
  mode?: string | null
  mission_id?: string | null
  roadmap_node_id?: string | null
  exercise_id?: string | null
  interview_id?: string | null
}

export interface InterviewBlueprintRequest {
  resume_id?: string
  job_profile_id?: number | null
  interview_mode: 'mock'
  interview_type: string
  profile_type: InterviewProfileType
}

export interface InterviewBlueprintSection {
  section_id: string
  label?: string
  kind?: string
  importance?: number
  taxonomy_keys?: string[]
  difficulty?: string
  time_budget_seconds?: number
  max_followups?: number
}

export interface InterviewBlueprint {
  blueprint_id: string
  status: 'ready' | 'consumed' | 'expired' | 'invalid' | string
  resume_id?: string
  job_profile_id?: number
  compiler_version?: string
  blueprint_hash?: string
  expires_at?: string | null
  created_at?: string | null
  preview?: {
    schema_version?: string
    compiler_version?: string
    blueprint_hash?: string
    job_target?: Record<string, unknown>
    interview_type?: string
    profile_type?: string
    experience_level?: string | null
    difficulty_level?: string
    duration_minutes?: number
    total_time_budget?: number
    round_config?: Record<string, unknown>
    sections?: InterviewBlueprintSection[]
  }
}

export async function createInterviewBlueprint(
  payload: InterviewBlueprintRequest,
  idempotencyKey: string,
): Promise<InterviewBlueprint> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.BLUEPRINTS}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({ ...payload, request_idempotency_key: idempotencyKey }),
      },
    )
    const data = await response.json()
    return data.blueprint || data
  } catch (error) {
    throw {
      code: 'BLUEPRINT_CREATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Could not prepare the interview',
    } as ApiError
  }
}

export async function fetchInterviewBlueprint(blueprintId: string): Promise<InterviewBlueprint> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.BLUEPRINTS}/${encodeURIComponent(blueprintId)}`,
      { method: 'GET' },
    )
    const data = await response.json()
    return data.blueprint || data
  } catch (error) {
    throw {
      code: 'BLUEPRINT_GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Could not load the interview preparation',
    } as ApiError
  }
}

export async function startInterviewFromBlueprint(
  blueprintId: string,
  idempotencyKey: string,
  runtime?: { input_mode?: 'voice' | 'text' | 'voice_or_text'; camera_mode?: 'off' | 'optional'; preflight_id?: string },
) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.START}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({ blueprint_id: blueprintId, start_idempotency_key: idempotencyKey, ...runtime }),
      },
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'START_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to start interview session',
    } as ApiError
  }
}

export interface LearningExercise {
  exercise_id: string
  interview_id: string | null
  skill_key: string | null
  source_response_id?: string | null
  exercise_type: string
  exercise_mode?: string
  input_type?: string
  timer_seconds?: number | null
  title: string
  prompt: {
    mode?: string
    input_type?: string
    timer_seconds?: number | null
    title?: string
    prompt?: string
    question?: string
    weak_answer?: string
    strong_shape?: string[]
    constraints?: string[]
    rubric_version?: string
    interaction_type?: string
    steps?: string[]
    language?: string
    code_excerpt?: string
    error_signature?: string
    legacy_coach_exercise?: boolean
  }
  rubric: Record<string, any>
  source_evidence: any[]
  status: string
  drill?: {
    canonical_drill: string
    category: 'interview' | 'coding' | 'resume' | string
    goal: string
    mistake_found: string
    evidence_from_report: string
    user_task: string
    found_from: string
    retest_nav: 'interview' | 'coding' | string
  }
  metadata?: Record<string, any>
  mission_id?: string | null
  mission_skill_id?: string | null
  roadmap_node_id?: string | null
  activity_type?: string | null
  variation_group?: string | null
  is_checkpoint?: boolean
  activity_metadata?: Record<string, any>
  created_at: string | null
  completed_at: string | null
}

export interface CoachingFeedback {
  summary?: string
  strengths?: string[]
  improvements?: string[]
  specific_feedback?: string
  mistake?: {
    type?: string
    quote?: string
    diagnosis?: string
  }
  why_bad?: string
  better_structure?: string[]
  improved_answer?: string
  next_drills?: {
    mode: string
    title: string
    reason: string
    success_criteria?: string[]
    target_skill_key?: string
  }[]
  retry_instruction?: string
  progress_signal?: string
  progress_delta?: number | null
}

export interface ExerciseAttemptResult {
  attempt_id: string
  exercise_id: string
  score: number
  passed: boolean
  mastery_passed: boolean
  specific_feedback?: string
  feedback?: CoachingFeedback
  next_drills?: CoachingFeedback['next_drills']
  progress_signal?: string
  next_review_at?: string
  next_review_time?: string
  updated_mastery?: Record<string, any>
  result_status?: string
  condition_results?: { id?: string; label?: string; met?: boolean; evidence?: string }[]
  passed_conditions?: string[]
  failed_conditions?: string[]
  score_components?: Record<string, any>
  mission_progress?: Record<string, any>
}

export interface ImproveSkill {
  mission_skill_id: string
  skill_key: string
  label: string
  category: string
  baseline_score: number
  latest_score: number
  target_score: number
  role_weight: number
  mastery_status: 'untrained' | 'practising' | 'ready_for_checkpoint' | 'held_out_passed' | 'verified' | 'needs_reinforcement' | string
  evidence_summary?: string | null
  criteria?: Record<string, any>
  verified_at?: string | null
  needs_reinforcement_at?: string | null
}

export interface ImproveRoadmapNode {
  roadmap_node_id: string
  mission_skill_id?: string | null
  exercise_id?: string | null
  recovery_of_node_id?: string | null
  order_index: number
  title: string
  description?: string | null
  activity_type: string
  availability_status: 'locked' | 'blocked' | 'unlocked' | 'current' | 'completed' | 'archived' | string
  attempt_status: 'draft' | 'in_progress' | 'submitted' | 'save_failed' | 'abandoned' | string
  result_status: 'not_attempted' | 'failed' | 'partial_pass' | 'passed' | 'strong_pass' | string
  mastery_status: 'untrained' | 'practising' | 'ready_for_checkpoint' | 'held_out_passed' | 'verified' | 'needs_reinforcement' | string
  estimated_minutes: number
  expected_result?: string | null
  evidence?: Record<string, any>
  completed_at?: string | null
  activity?: Record<string, any> | null
  rubric?: Record<string, any>
  exercise_status?: string | null
}

export interface ImproveAttemptSession {
  attempt_session_id: string
  mission_id: string
  roadmap_node_id: string
  exercise_id: string
  status: string
  draft_payload: Record<string, any>
  idempotency_key: string
  deadline_at?: string | null
  remaining_seconds?: number | null
  updated_at?: string | null
  expires_at?: string | null
}

export interface ActiveImproveMission {
  mission_id: string
  mission_type: string
  mode?: 'interview' | 'technical' | 'mock' | string
  title: string
  assignment_reason: string
  diagnosis: Record<string, any>
  weakness_key?: string | null
  weakness_type?: string | null
  priority_score: number
  priority_factors: Record<string, any>
  baseline_readiness: number
  current_readiness: number
  target_readiness: number
  progress_percent: number
  status: string
  prediction?: Record<string, any>
  validation_status?: string | null
  validated_by_interview_id?: string | null
  source_interview_id?: string | null
  source_analysis_id?: string | null
  report_path?: string | null
  created_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
  skills: ImproveSkill[]
  roadmap: ImproveRoadmapNode[]
  active_attempt_session?: ImproveAttemptSession | null
  primary_action?: {
    action: 'continue' | 'official_reassessment' | 'none' | string
    roadmap_node_id?: string | null
    exercise_id?: string | null
    label: string
  }
}

export interface ImprovementHistory {
  skills: {
    skill_key: string
    label: string
    mode?: 'interview' | 'technical' | 'mock' | string | null
    weakness_key?: string | null
    weakness_type?: string | null
    baseline_score: number
    latest_score: number
    improvement: number
    verification_status: string
    verified_at?: string | null
    needs_reinforcement_at?: string | null
    attempt_count: number
    last_attempt_at?: string | null
    latest_checkpoint_score?: number | null
    baseline_source?: string
  }[]
  completed_missions: {
    mission_id: string
    title: string
    baseline_readiness: number
    current_readiness: number
    target_readiness: number
    progress_percent: number
    status: string
    mode?: 'interview' | 'technical' | 'mock' | string | null
    weakness_key?: string | null
    weakness_type?: string | null
    completed_at?: string | null
    improvement: number
  }[]
  recent_attempts: {
    attempt_id: string
    exercise_id: string
    mission_id?: string | null
    roadmap_node_id?: string | null
    activity_type?: string | null
    score: number
    passed: boolean
    is_checkpoint: boolean
    created_at?: string | null
    condition_results?: any[]
    skill_key?: string | null
    mode?: 'interview' | 'technical' | 'mock' | string | null
  }[]
  has_history: boolean
}

export interface LearningDashboard {
  next_action?: ImproveNextAction | null
  student_summary: {
    headline: string
    blocker: string
    next_step: string
    integrity: string
  }
  completed_fixes?: {
    area: string
    before: string
    after: string
    score?: number | null
    completed_at?: string | null
  }[]
  practice_loop?: {
    active_drill?: LearningExercise | null
    latest_attempt?: {
      skill_key: string | null
      exercise_type: string
      score: number
      mistake_type: string
      mastery_passed: boolean
      created_at: string | null
      progress_signal?: string | null
    } | null
    repeated_mistake?: string | null
    progress_summary?: string
    mode_stats?: {
      mode: string
      attempt_count: number
      pass_rate: number
      latest_score: number
      score_delta?: number | null
    }[]
  }
  skill_gaps: {
    skill_key: string
    label: string
    category: string
    mastery_score: number
    confidence_score: number
    evidence_count: number
    last_evidence_at: string | null
    next_review_at: string | null
    why_it_matters: string
    last_attempt_score?: number
    repeated_mistake?: string
    trend_label?: string
  }[]
  technical_mistakes: {
    cluster_id: number
    round_id: string
    mistake_type: string
    mistake_key: string
    summary: string
    repair_action: string
    examples: any[]
    occurrence_count: number
    last_seen_at: string | null
  }[]
  project_homework: {
    gap_id: number
    project_key: string
    gap_key: string
    title: string
    evidence: any
    status: string
    next_check_at: string | null
    updated_at: string | null
  }[]
  exercise_queue: LearningExercise[]
  active_mission?: ActiveImproveMission | null
  active_missions?: {
    interview?: ActiveImproveMission | null
    technical?: ActiveImproveMission | null
  }
  roadmap?: ImproveRoadmapNode[]
  improvement_history?: ImprovementHistory
  integrity_status: {
    status: string
    mode?: "self_review" | string
    severe_count: number
    warning_count: number
    signal_count?: number
    events: { event_type: string; severity: string; count: number; last_seen_at: string | null }[]
  }
  analysis_availability?: {
    completed_count: number
    missing_canonical_count: number
    performance_ready?: boolean
    performance_ready_count?: number
    comparison_ready?: boolean
    improve_available?: boolean
  }
  performance_ready?: boolean
  comparison_ready?: boolean
  improve_available?: boolean
}

export async function fetchLearningDashboard(): Promise<LearningDashboard> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.LEARNING}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve learning dashboard',
    } as ApiError
  }
}

export async function submitExerciseAttempt(exerciseId: string, payload: {
  mission_id: string
  roadmap_node_id: string
  submitted_answer?: string
  submitted_payload?: Record<string, any>
  idempotency_key: string
  attempt_session_id: string
}): Promise<ExerciseAttemptResult> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.EXERCISE_ATTEMPT}/${exerciseId}/attempt`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(payload.idempotency_key ? { 'Idempotency-Key': payload.idempotency_key } : {}),
        },
        body: JSON.stringify(payload),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'ATTEMPT_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to submit exercise attempt',
    } as ApiError
  }
}

export async function createExerciseAttemptSession(exerciseId: string, payload: {
  mission_id: string
  roadmap_node_id: string
  draft_payload?: Record<string, any>
  idempotency_key: string
}): Promise<ImproveAttemptSession> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.EXERCISE_ATTEMPT}/${exerciseId}/attempt-session`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': payload.idempotency_key,
        },
        body: JSON.stringify(payload),
      }
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'ATTEMPT_SESSION_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to start activity attempt',
    } as ApiError
  }
}

export async function updateExerciseAttemptSession(exerciseId: string, attemptSessionId: string, payload: {
  mission_id: string
  roadmap_node_id: string
  idempotency_key: string
  status?: 'draft' | 'in_progress' | 'save_failed' | 'abandoned'
  draft_payload?: Record<string, any>
}): Promise<ImproveAttemptSession> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.EXERCISE_ATTEMPT}/${exerciseId}/attempt-session/${attemptSessionId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': payload.idempotency_key,
        },
        body: JSON.stringify(payload),
      }
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'ATTEMPT_SESSION_UPDATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to save activity draft',
    } as ApiError
  }
}

export interface ExerciseRunResult {
  exercise_id: string
  language: 'python' | 'javascript' | 'java'
  stdout: string
  stderr: string
  exit_code: number | null
  runtime_ms: number
  error_signature: string
}

export async function runExerciseCode(exerciseId: string, payload: {
  language: 'python' | 'javascript' | 'java'
  code: string
  stdin?: string
}): Promise<ExerciseRunResult> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.EXERCISE_RUN}/${exerciseId}/run`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'RUN_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to run exercise code',
    } as ApiError
  }
}

export async function fetchRecentActivity(days: number = 30) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.RECENT_ACTIVITY}?days=${days}`,
      {
        method: 'GET',
      }
    )

    if (!response.ok) {
      throw new Error(`Fetch failed: ${response.statusText}`)
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve recent activity',
    } as ApiError
  }
}

export interface JobProfile {
  profile_id: number
  role: string
  company: string | null
  tech_stack: string[]
  job_description?: string | null
  job_description_hash?: string | null
  experience_level?: string | null
  normalized_requirements?: Record<string, unknown> | unknown[] | null
  normalization_version?: string | null
  parser_version?: string | null
  is_selected: boolean
  created_at: string
  updated_at?: string | null
}

export interface JobProfileInput {
  role: string
  company?: string
  tech_stack?: string[]
  job_description?: string
  experience_level?: string
  normalized_requirements?: Record<string, unknown> | unknown[]
}

export type InterviewProfileType = 'top_tier' | 'mid_tier' | 'startup' | 'custom'

export interface InterviewProfileOption {
  profile_type: InterviewProfileType
  label: string
  interview_instruction: string
  technical_instruction: string
  behavioral_instruction?: string
  duration?: {
    min_minutes: number
    target_minutes: number
    max_minutes: number
  }
}

export interface InterviewProfileResponse {
  profile_type: InterviewProfileType
  label: string
  options: InterviewProfileOption[]
}

export async function fetchInterviewProfile(): Promise<InterviewProfileResponse> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.INTERVIEW_PROFILE}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve interview profile',
    } as ApiError
  }
}

export async function updateInterviewProfile(profileType: InterviewProfileType): Promise<InterviewProfileResponse> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.INTERVIEW_PROFILE}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ profile_type: profileType }),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'UPDATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to update interview profile',
    } as ApiError
  }
}

export async function fetchJobProfiles(): Promise<JobProfile[]> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve job profiles',
    } as ApiError
  }
}

export async function createJobProfile(payload: JobProfileInput): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'CREATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to create job profile',
    } as ApiError
  }
}

export async function updateJobProfile(profileId: number, payload: Partial<JobProfileInput>): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}/${profileId}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'JOB_PROFILE_UPDATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to update job target',
    } as ApiError
  }
}

export async function deleteJobProfile(profileId: number): Promise<void> {
  try {
    await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}/${profileId}`,
      { method: 'DELETE' },
    )
  } catch (error) {
    throw {
      code: 'JOB_PROFILE_DELETE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to delete job target',
    } as ApiError
  }
}

export async function copyInterviewJobProfile(interviewId: string): Promise<{ profile: JobProfile; created: boolean }> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/workspace/interviews/${encodeURIComponent(interviewId)}/copy-profile`,
      { method: 'POST' },
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'JOB_PROFILE_COPY_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to copy interview profile',
    } as ApiError
  }
}

export async function selectJobProfile(profileId: number): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}/${profileId}/select`,
      {
        method: 'POST',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'SELECT_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to select job profile',
    } as ApiError
  }
}

export async function startInterviewSession(
  mode: 'mock',
  type: string,
  profileType?: InterviewProfileType,
  jobProfileId?: number,
  jobId?: number,
  customJobTitle?: string,
  customJobDescription?: string,
  companyName?: string
) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.START}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          interview_mode: mode,
          interview_type: type,
          profile_type: profileType || null,
          job_profile_id: jobProfileId || null,
          job_id: jobId || null,
          custom_job_title: customJobTitle || null,
          custom_job_description: customJobDescription || null,
          company_name: companyName || null
        }),
      }
    )

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(error.detail || error.message || 'Failed to start session'))
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'START_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to start interview session',
    } as ApiError
  }
}

export async function endInterviewSession(interviewId: string, options: { keepalive?: boolean } = {}) {
  try {
    const response = await fetch(
      `${API_CONFIG.BASE_URL}/interview/${interviewId}/end`,
      {
        method: 'POST',
        keepalive: options.keepalive,
      }
    )

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(error.detail || error.message || 'Failed to end interview session'))
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'END_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to end interview session',
    } as ApiError
  }
}

export async function prepareTechnicalRounds(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/technical/sessions/${interviewId}/prepare`,
      {
        method: 'POST',
        headers: {
          'Idempotency-Key': `technical-prepare-${interviewId}`,
        },
      }
    )

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(error.detail || error.message || 'Failed to prepare technical round'))
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'TECHNICAL_PREPARE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to prepare technical round',
    } as ApiError
  }
}

export async function activateTechnicalRound(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/technical/sessions/${interviewId}/activate`,
      {
        method: 'POST',
        headers: {
          'Idempotency-Key': `technical-activate-${interviewId}`,
        },
      },
    )
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(error.detail || error.message || 'Failed to activate technical round'))
    }
    return await response.json()
  } catch (error) {
    throw {
      code: 'TECHNICAL_ACTIVATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to activate technical round',
    } as ApiError
  }
}

export async function cancelInterviewSession(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.CANCEL}/${interviewId}`,
      {
        method: 'DELETE',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'CANCEL_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to cancel interview session',
    } as ApiError
  }
}

export async function abandonInterviewSession(
  interviewId: string,
  options: { keepalive?: boolean } = {},
) {
  try {
    const response = await fetch(
      `${API_CONFIG.BASE_URL}/interview/${interviewId}/abandon`,
      {
        method: 'POST',
        keepalive: options.keepalive,
      },
    )
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(error.detail || error.message || 'Failed to end interview attempt'))
    }
    return await response.json()
  } catch (error) {
    throw {
      code: 'ABANDON_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to end interview attempt',
    } as ApiError
  }
}

export async function fetchInterviewStatus(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.STATUS}/${interviewId}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve interview status',
    } as ApiError
  }
}

export async function fetchInterviewReport(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.REPORT}/${interviewId}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve interview report',
    } as ApiError
  }
}

export async function downloadInterviewReportJson(interviewId: string): Promise<void> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/interview/report/${interviewId}/export`,
    {
      method: 'GET',
    },
  )
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/)?.[1] || `prepmate-report-${interviewId}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}

export interface InterviewAnalysisStatus {
  interview_id: string
  status: string
  overall_score: number | null
  completed_at: string | null
  report_ready: boolean
  report_state?: "generating" | "retrying" | "ready" | "partial" | "failed" | "ungradable" | string
  analysis_status?: string
  attempt_status?: string
  execution_pending?: boolean
  processing_sla_minutes?: number
  retry_in_progress?: boolean
  retryable?: boolean
  job: {
    job_id: string
    status: string
    current_stage: string | null
    progress: number
    error_message: string | null
    updated_at: string | null
    retry_count?: number
    manual_retry_count?: number
  } | null
}

export async function fetchInterviewAnalysisStatus(interviewId: string): Promise<InterviewAnalysisStatus> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.ANALYSIS_STATUS}/${interviewId}/analysis-status`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve analysis status',
    } as ApiError
  }
}

export async function retryInterviewAnalysis(interviewId: string): Promise<{ job_id: string; status: string; manual_retry_count: number }> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.ANALYSIS_STATUS}/${interviewId}/analysis/retry`,
      {
        method: 'POST',
      },
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'RETRY_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retry report analysis',
    } as ApiError
  }
}

export interface DynamicPerformanceMetric {
  label: string
  value?: string | number | null
  raw_value?: number | null
  detail?: string | null
}

export interface DynamicPerformanceSection {
  id: string
  title: string
  kind: 'metrics' | 'score_rows' | 'table' | 'trend' | string
  description?: string | null
  columns?: { key: string; label: string }[]
  rows?: Record<string, any>[]
  metrics?: DynamicPerformanceMetric[]
  items?: Record<string, any>[]
  comparison?: {
    taxonomy_version?: string | null
    rubric_version?: string | null
    evaluator_version?: string | null
    comparison_key?: string | null
  }
  trend?: {
    label?: string | null
    date?: string | null
    analysis_id?: string
    score?: number | null
    interview_id?: string
    round_id?: string
    response_id?: string
    evidence_id?: string
    evidence_ids?: string[]
    evidence_url?: string
    taxonomy_version?: string | null
    rubric_version?: string | null
    evaluator_version?: string | null
  }[]
}

export interface PerformanceTrendPoint {
  label?: string | null
  date?: string | null
  score?: number | null
  interview_id?: string
  round_id?: string
  response_id?: string
  evidence_id?: string
  evidence_url?: string
  source_kind?: "canonical_v4" | "recorded_evidence" | "legacy_report" | string
  score_state?: "ready" | "processing" | "blocked" | "failed" | "insufficient" | "run_only" | "legacy" | "missing" | string
  included_in_trend?: boolean
  detail?: string | null
  mode?: "interview" | "technical" | string
  role?: string | null
}

export interface PerformancePattern {
  label: string
  detail?: string | null
  count?: number
  session_count?: number
  recurring?: boolean
  score?: number | null
}

export interface PerformanceDirection {
  label: string
  delta: number
  latest_score?: number | null
  session_count?: number
}

export interface PerformanceRoundHistoryItem {
  interview_id?: string | null
  mode: 'interview' | 'technical' | string
  role?: string | null
  company?: string | null
  completed_at?: string | null
  date?: string | null
  score?: number | null
  duration_seconds?: number | null
  score_state?: string | null
  source_kind?: string | null
  included_in_trend?: boolean
  round_id?: string | null
  change?: number | null
  key_result?: string | null
  questions_completed?: number | null
  questions_total?: number | null
  questions_skipped?: number | null
  problems_attempted?: number | null
  problems_total?: number | null
  problems_solved?: number | null
  problems_partially_solved?: number | null
  problems_not_submitted?: number | null
  problems_not_attempted?: number | null
  languages?: string[]
  report_path?: string | null
  evidence_ids?: string[]
  summary?: string | null
  takeaway?: string | null
  strengths?: PerformanceRoundFinding[]
  issues?: PerformanceRoundFinding[]
  mistakes?: PerformanceRoundFinding[]
}

export interface PerformanceRoundFinding {
    label?: string | null
    source_label?: string | null
    detail?: string | null
    what_happened?: string | null
    why_it_matters?: string | null
    evidence_ids?: string[]
    status?: string | null
    score?: number | null
    response_id?: string | null
    round_id?: string | null
}

export interface PerformanceAnalytics {
  summary?: {
    total_rounds?: number
    total_reports?: number
    official_reports?: number
    average_score?: number | null
    latest_score?: number | null
    best_score?: number | null
    recent_change?: number | null
    average_duration_seconds?: number | null
    trend?: string | null
    problems_attempted?: number
    problems_total?: number
    problems_solved?: number
    submission_rate?: number | null
  }
  report_findings?: {
    summary?: {
      total_reports?: number
      official_reports?: number
      reports_with_findings?: number
      reports_with_issues?: number
      reports_with_strengths?: number
      issue_count?: number
      strength_count?: number
      recurring_issue_count?: number
    }
    takeaway?: string | null
    issues?: Record<string, any>[]
    strengths?: Record<string, any>[]
  }
  skills?: Record<string, any>[]
  topics?: Record<string, any>[]
  question_types?: Record<string, any>[]
  patterns?: Record<string, any>[]
  test_patterns?: Record<string, any>[]
  behavior?: Record<string, any>[]
  tests?: Record<string, any>[]
  submission?: Record<string, any>
  time?: Record<string, any>[]
  time_patterns?: Record<string, any>[]
  complexity?: Record<string, any>[]
  follow_up?: Record<string, any>
  improvement?: {
    improving?: Record<string, any>[]
    declining?: Record<string, any>[]
    stable?: Record<string, any>[]
  }
}

export interface PerformanceScoreDetail {
  score?: number | null
  detail?: string | null
}

export interface PerformanceProjectExplanation extends PerformanceScoreDetail {
  answer_count?: number
  session_count?: number
  breakdown?: { label: string; score?: number | null }[]
}

export interface PerformancePagePayload {
  role: {
    role?: string | null
    company?: string | null
  }
  interview_view?: {
    latest_score?: number | null
    trend: PerformanceTrendPoint[]
    communication: {
      fluency_clarity: PerformanceScoreDetail
      confidence: PerformanceScoreDetail
      patterns: PerformancePattern[]
    }
    project_explanation: PerformanceProjectExplanation
    insights: {
      recurring_mistakes: PerformancePattern[]
      improving: PerformanceDirection[]
      declining: PerformanceDirection[]
    }
    strengths: string[]
  }
  technical_view?: {
    latest_score?: number | null
    trend: PerformanceTrendPoint[]
    knowledge_gaps: PerformancePattern[]
    insights: {
      recurring_mistakes: PerformancePattern[]
      improving: PerformanceDirection[]
      declining: PerformanceDirection[]
    }
    strengths: string[]
  }
  overall: {
    latest_interview_score?: number | null
    performance_trend: PerformanceTrendPoint[]
    readiness: {
      score?: number | null
      label: string
      role?: string | null
      detail?: string | null
      components?: {
        key: string
        label: string
        score?: number | null
        weight: number
      }[]
    }
  }
  communication: {
    fluency_clarity: PerformanceScoreDetail
    confidence: PerformanceScoreDetail
    patterns: PerformancePattern[]
  }
  technical: {
    trend: PerformanceTrendPoint[]
    latest_score?: number | null
    knowledge_gaps: PerformancePattern[]
    project_explanation: PerformanceProjectExplanation
  }
  insights: {
    recurring_mistakes: PerformancePattern[]
    improving: PerformanceDirection[]
    declining: PerformanceDirection[]
    ai_insights: string[]
  }
  strengths: string[]
}

export interface DynamicPerformancePayload {
  mode: 'interview' | 'technical' | string
  has_data: boolean
  overview: DynamicPerformanceMetric[]
  sections: DynamicPerformanceSection[]
  next_focus?: {
    title: string
    description?: string | null
    source?: string | null
  } | null
  comparison_notice?: string | null
  source?: 'canonical' | 'legacy' | string
  analysis_id?: string | null
  interview_id?: string | null
  official_analysis_id?: string | null
  official_interview_id?: string | null
  official_score?: number | null
  official_scored_at?: string | null
  overall_score?: number | null
  duration_seconds?: number | null
  evidence_status?: string | null
  evidence_index?: Record<string, unknown> | null
  current_value?: number | null
  confidence?: "high" | "medium" | "low" | "insufficient" | string
  evidence_count?: number
  time_window?: { from?: string | null; to?: string | null }
  source_analysis_ids?: string[]
  next_recommended_focus?: { title: string; description?: string | null; source?: string | null } | null
  empty_state_explanation?: string | null
  comparability?: {
    taxonomy_version?: string | null
    rubric_version?: string | null
    evaluator_version?: string | null
    profile_family?: string | null
    evidence_status?: string | null
    cohort_id?: string | null
    comparable_analysis_count?: number
    excluded_incompatible_count?: number
  } | null
  trend?: DynamicPerformanceSection['trend']
  page_summary?: Record<string, unknown>
  has_evidence?: boolean
  has_official_score?: boolean
  score_state?: "ready" | "processing" | "blocked" | "failed" | "insufficient" | "run_only" | "legacy" | "missing" | string
  source_kind?: "canonical_v4" | "recorded_evidence" | "legacy_report" | "unavailable" | string
  included_in_trend?: boolean
  round_history?: PerformanceRoundHistoryItem[]
  comparison_ready?: boolean
  improve_available?: boolean
  analytics?: PerformanceAnalytics
}

export interface PerformanceData {
  interview: DynamicPerformancePayload
  technical: DynamicPerformancePayload
  page?: PerformancePagePayload
  history?: {
    official: PerformanceTrendPoint[]
    legacy: PerformanceTrendPoint[]
  }
  round_history?: PerformanceRoundHistoryItem[]
  comparison_ready?: boolean
  improve_available?: boolean
  availability?: {
    completed_count: number
    missing_canonical_count: number
    pending_count: number
    blocked_count?: number
    failed_count: number
    worker_available?: boolean
    processing_sla_minutes?: number
    by_mode?: Record<string, {
      completed_count: number
      ready: number
      processing: number
      blocked: number
      failed: number
      insufficient: number
      run_only: number
      legacy: number
      missing: number
    }>
    sessions?: {
      interview_id: string
      mode: string
      score_state: string
      analysis_id?: string | null
      job_status?: string | null
      retry_count?: number
      has_evidence?: boolean
      has_official_score?: boolean
    }[]
  }
}

export interface PerformanceReconcileResult {
  status: string
  queued_count: number
  already_running_count?: number
  retry_exhausted_count?: number
  rejected_count?: number
  ready_count?: number
  processing_sla_minutes?: number
  next_cursor?: string | null
  has_more?: boolean
}

export async function reconcilePerformance(cursor?: string | null): Promise<PerformanceReconcileResult> {
  try {
    const search = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.ANALYSIS.RECONCILE_PERFORMANCE}${search}`,
      { method: 'POST' },
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'RECONCILE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to prepare performance analysis',
    } as ApiError
  }
}

export async function fetchPerformance(): Promise<PerformanceData> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.PERFORMANCE}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve performance',
    } as ApiError
  }
}

export interface TechnicalRoundHistoryItem {
  round_id: string
  interview_id: string
  round_type: string
  language: string | null
  prompt: string
  status: string
  created_at: string | null
  completed_at: string | null
  run_count: number
  successful_runs: number
  avg_runtime_ms: number
  last_run_at: string | null
  profile_type?: string
  title?: string
  hidden_passed?: number | null
  hidden_total?: number | null
  visible_passed?: number | null
  visible_total?: number | null
  final_verdict?: string | null
  submitted_at?: string | null
}

export interface TechnicalRoundSession {
  interview_id: string
  profile_type?: string | null
  job_title?: string | null
  interview_status?: string | null
  interview_completed_at?: string | null
  duration_seconds?: number | null
  official_score?: number | null
  cta?: {
    label?: string
    nav?: string
    entity_id?: string | null
  }
  rounds: TechnicalRoundHistoryItem[]
}

export async function fetchTechnicalRoundHistory(): Promise<{ rounds: TechnicalRoundHistoryItem[]; sessions?: TechnicalRoundSession[]; total_count: number }> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.TECHNICAL_ROUNDS}`,
      {
        method: 'GET',
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve technical rounds',
    } as ApiError
  }
}

export interface LocalProviderSettings {
  provider: string
  model: string
  endpoint: string
  has_api_key: boolean
  requires_api_key?: boolean
}

export async function fetchLocalSettings(): Promise<LocalProviderSettings> {
  const response = await fetchWithRetry(`${API_CONFIG.BASE_URL}/local/settings`, { method: "GET" })
  return await response.json()
}

export async function fetchRedactedDiagnostics(): Promise<Record<string, unknown>> {
  const response = await fetchWithRetry(`${API_CONFIG.BASE_URL}/local/diagnostics`, { method: "GET" })
  return await response.json()
}

export async function downloadUserDataExport(): Promise<void> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/profile/export-data`,
    { method: 'GET' },
  )
  const payload = await response.blob()
  const url = URL.createObjectURL(payload)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `prepmate-data-export-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function deleteSessionHistory(): Promise<{ interviews_deleted?: number; deleted_counts?: Record<string, number> }> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/profile/session-history`,
    { method: 'DELETE' },
  )
  return await response.json()
}

export async function deleteResumeData(): Promise<{ message?: string }> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/profile/resume`,
    { method: 'DELETE' },
  )
  return await response.json()
}

export async function deleteAllProviderKeys(): Promise<void> {
  await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/local/settings/keys`,
    { method: 'DELETE' },
  )
}

export async function clearLocalCaches(): Promise<{ data_directory?: string; removed?: string[] }> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/local/data/cache/clear`,
    { method: 'POST' },
  )
  return await response.json()
}

export async function wipeAllLocalData(): Promise<{ data_directory?: string; removed?: string[]; database_recreated?: boolean }> {
  const response = await fetchWithRetry(
    `${API_CONFIG.BASE_URL}/local/data/wipe`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: 'WIPE' }),
    },
  )
  return await response.json()
}
