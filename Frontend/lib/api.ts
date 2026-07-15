import { API_CONFIG, API_ENDPOINTS } from './config'
import { getAuthHeaders } from './auth'
import type {
  ResumeData,
  UploadResponse,
  SubmitResponse,
  ApiError,
} from '@/types/resume'

function friendlyMessage(raw: string): string {
  const lower = raw.toLowerCase()
  if (
    lower.includes('no interviews remaining') ||
    lower.includes('no credits') ||
    lower.includes('limit reached') ||
    lower.includes('technical rounds are locked') ||
    lower.includes('requires the premium plan') ||
    lower.includes('require the premium plan') ||
    lower.includes('require the pro or premium plan') ||
    lower.includes('your plan includes') ||
    lower.includes('upgrade your plan')
  ) return raw
  if (lower.includes('forbidden') || lower.includes('403')) return 'Access denied. Please log in again.'
  if (lower.includes('unauthorized') || lower.includes('401')) return 'Session expired. Please log in again.'
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
      credentials: 'include',
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
  ready: boolean
  status: 'ready' | 'not_ready' | string
  message: string
  recovery_grace_seconds: number
  checks: Record<string, { healthy?: boolean; [key: string]: unknown }>
}

export async function fetchFlowPreflight(flow: 'interview' | 'technical'): Promise<FlowPreflightStatus> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT)
  try {
    const response = await fetch(`${API_CONFIG.BASE_URL}/preflight?flow=${flow}`, {
      credentials: 'include',
      headers: getAuthHeaders(),
      signal: controller.signal,
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok && response.status !== 503) {
      throw new Error(friendlyMessage(payload?.detail || payload?.message || `HTTP ${response.status}`))
    }
    if (!payload || typeof payload.ready !== 'boolean') {
      throw new Error('The service readiness response was invalid.')
    }
    return payload
  } catch (error) {
    if (error instanceof Error) throw new Error(friendlyMessage(error.message))
    throw new Error('Service readiness could not be checked.')
  } finally {
    clearTimeout(timeoutId)
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
  camera_ready: boolean
  microphone_ready: boolean
  microphone_level_detected: boolean
  screen_share_ready: boolean
  network_ready: boolean
  error_codes?: string[]
}): Promise<PersistedPreflight> {
  const response = await fetchWithRetry(`${API_CONFIG.BASE_URL}/preflight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function uploadResume(file: File): Promise<{ uploadResponse: UploadResponse; parsedData: ResumeData }> {
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.RESUME.UPLOAD}`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          ...getAuthHeaders(),
        },
        body: formData,
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(body.detail || body.message || 'Upload failed'))
    }

    const data = await response.json()

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
    throw {
      code: 'UPLOAD_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to upload resume',
    } as ApiError
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
          ...getAuthHeaders(),
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
        headers: {
          ...getAuthHeaders(),
        },
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
      { method: 'GET', headers: { ...getAuthHeaders() } },
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
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
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
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
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
          ...getAuthHeaders(),
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
      { method: 'GET', headers: { ...getAuthHeaders() } },
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
  runtime?: { input_mode?: 'voice' | 'text' | 'voice_or_text'; camera_mode?: 'off' | 'optional' | 'required'; preflight_id?: string },
) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.START}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
          ...getAuthHeaders(),
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
    severe_count: number
    warning_count: number
    events: { event_type: string; severity: string; count: number; last_seen_at: string | null }[]
  }
  analysis_availability?: {
    completed_count: number
    missing_canonical_count: number
  }
}

export async function fetchLearningDashboard(): Promise<LearningDashboard> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.LEARNING}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
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
          ...getAuthHeaders(),
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
          ...getAuthHeaders(),
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
          ...getAuthHeaders(),
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
          ...getAuthHeaders(),
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
        headers: {
          ...getAuthHeaders(),
        },
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
        headers: {
          ...getAuthHeaders(),
        },
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
          ...getAuthHeaders(),
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
        headers: {
          ...getAuthHeaders(),
        },
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
          ...getAuthHeaders(),
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
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
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
      { method: 'DELETE', headers: { ...getAuthHeaders() } },
    )
  } catch (error) {
    throw {
      code: 'JOB_PROFILE_DELETE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to delete job target',
    } as ApiError
  }
}

export async function selectJobProfile(profileId: number): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.WORKSPACE.JOB_PROFILES}/${profileId}/select`,
      {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
        },
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
          ...getAuthHeaders(),
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
        credentials: 'include',
        headers: {
          ...getAuthHeaders(),
        },
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
          ...getAuthHeaders(),
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

export async function cancelInterviewSession(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.CANCEL}/${interviewId}`,
      {
        method: 'DELETE',
        headers: {
          ...getAuthHeaders(),
        },
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

export async function fetchInterviewStatus(interviewId: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.INTERVIEW.STATUS}/${interviewId}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
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
        headers: {
          ...getAuthHeaders(),
        },
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

export interface InterviewAnalysisStatus {
  interview_id: string
  status: string
  overall_score: number | null
  completed_at: string | null
  report_ready: boolean
  report_state?: "generating" | "retrying" | "ready" | "partial" | "failed" | "ungradable" | string
  analysis_status?: string
  attempt_status?: string
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
        headers: {
          ...getAuthHeaders(),
        },
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
        headers: {
          ...getAuthHeaders(),
        },
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
}

export interface PerformanceData {
  interview: DynamicPerformancePayload
  technical: DynamicPerformancePayload
  availability?: {
    completed_count: number
    missing_canonical_count: number
    pending_count: number
    failed_count: number
  }
}

export async function reconcilePerformance(): Promise<{ status: string; queued_count: number }> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.ANALYSIS.RECONCILE_PERFORMANCE}`,
      { method: 'POST', headers: { ...getAuthHeaders() } },
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
        headers: {
          ...getAuthHeaders(),
        },
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
  interview_status?: string | null
  interview_completed_at?: string | null
  duration_seconds?: number | null
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
        headers: {
          ...getAuthHeaders(),
        },
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

export async function createSupportSubmission(payload: {
  kind: 'bug' | 'feedback'
  title?: string
  message: string
  steps?: string
  rating?: number
  interview_id?: string
  page_url?: string
}) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/workspace/support`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'SUPPORT_CREATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to submit support request',
    } as ApiError
  }
}

export async function fetchSupportSubmissions(statusFilter?: string) {
  try {
    const query = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/workspace/support/submissions${query}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'SUPPORT_LIST_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load support submissions',
    } as ApiError
  }
}

export async function updateSupportSubmission(submissionId: number, payload: { status?: string; admin_notes?: string }) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}/workspace/support/submissions/${submissionId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'SUPPORT_UPDATE_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to update support submission',
    } as ApiError
  }
}

export async function fetchPaymentTransactions(limit: number = 20) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PAYMENT.TRANSACTIONS}?limit=${limit}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'PAYMENT_TRANSACTIONS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load payment transactions',
    } as ApiError
  }
}

export async function fetchPaymentPlans() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PAYMENT.PLANS}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'PAYMENT_PLANS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load payment plans',
    } as ApiError
  }
}

export async function fetchEntitlements() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.ENTITLEMENTS}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )
    return await response.json()
  } catch (error) {
    throw {
      code: 'ENTITLEMENTS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load entitlements',
    } as ApiError
  }
}

export async function createPaymentSession(planType: string, provider: string = 'razorpay', paymentMethod: string = 'card', sessions?: number) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PAYMENT.CREATE_SUBSCRIPTION}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          plan_type: planType,
          provider: provider,
          payment_method: paymentMethod,
          sessions: sessions
        }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(body.detail || body.message || 'Payment failed'))
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'PAYMENT_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to create payment session',
    } as ApiError
  }
}

export async function verifyRazorpayPayment(orderId: string, paymentId: string, signature: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PAYMENT.VERIFY_RAZORPAY}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          razorpay_order_id: orderId,
          razorpay_payment_id: paymentId,
          razorpay_signature: signature,
        }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Payment verification failed')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'VERIFICATION_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Payment verification failed',
    } as ApiError
  }
}

export async function changePassword(currentPassword: string, newPassword: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.CHANGE_PASSWORD}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to change password')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'CHANGE_PASSWORD_FAILED',
      message: error instanceof Error ? error.message : 'Failed to change password',
    } as ApiError
  }
}

export async function deleteAccount(password?: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.DELETE_ACCOUNT}`,
      {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ password: password || null }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to delete account')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'DELETE_ACCOUNT_FAILED',
      message: error instanceof Error ? error.message : 'Failed to delete account',
    } as ApiError
  }
}

export async function updateAccountInfo(fullName?: string, email?: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.UPDATE_ACCOUNT}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ full_name: fullName || null, email: email || null }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to update account')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'UPDATE_ACCOUNT_FAILED',
      message: error instanceof Error ? error.message : 'Failed to update account info',
    } as ApiError
  }
}

export async function uploadAvatar(base64Data: string) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.AVATAR}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ avatar_data: base64Data }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to upload avatar')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'AVATAR_UPLOAD_FAILED',
      message: error instanceof Error ? error.message : 'Failed to upload avatar',
    } as ApiError
  }
}

export async function exportUserData() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.EXPORT_DATA}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )

    if (!response.ok) {
      throw new Error('Failed to export data')
    }

    const data = await response.json()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `interai-data-export-${new Date().toISOString().split('T')[0]}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    return data
  } catch (error) {
    throw {
      code: 'EXPORT_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to export data',
    } as ApiError
  }
}

export async function deleteSessionHistory() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.DELETE_SESSION_HISTORY}`,
      {
        method: 'DELETE',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to delete session history')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'DELETE_HISTORY_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to delete session history',
    } as ApiError
  }
}

export interface NotificationPrefs {
  inactive_reminder_days: number | null
  target_date: string | null
  weekly_summary: boolean
  streak_reminder: boolean
}

export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.NOTIFICATION_PREFS}`,
      {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      }
    )

    return await response.json()
  } catch (error) {
    throw {
      code: 'GET_PREFS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to load notification preferences',
    } as ApiError
  }
}

export async function updateNotificationPrefs(prefs: NotificationPrefs) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.NOTIFICATION_PREFS}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(prefs),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Failed to save notification preferences')
    }

    return await response.json()
  } catch (error) {
    throw {
      code: 'UPDATE_PREFS_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to save notification preferences',
    } as ApiError
  }
}
