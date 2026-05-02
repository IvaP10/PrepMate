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
  if (lower.includes('no interviews remaining') || lower.includes('no credits')) return raw
  if (lower.includes('forbidden') || lower.includes('403')) return 'Access denied. Please log in again.'
  if (lower.includes('unauthorized') || lower.includes('401')) return 'Session expired. Please log in again.'
  if (lower.includes('not found') || lower.includes('404')) return 'The requested resource was not found.'
  if (lower.includes('429') || lower.includes('too many')) return 'Too many requests. Please wait a moment.'
  if (lower.includes('500') || lower.includes('internal server')) return 'Something went wrong. Please try again.'
  if (lower.includes('network') || lower.includes('failed to fetch') || lower.includes('abort')) return 'Connection issue. Check your network and try again.'
  if (lower.startsWith('http ')) return 'Something went wrong. Please try again.'
  return raw
}

async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  retries: number = API_CONFIG.RETRY_ATTEMPTS
): Promise<Response> {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT)

    const response = await fetch(url, {
      ...options,
      credentials: 'include',
      signal: controller.signal,
    })

    clearTimeout(timeoutId)

    if (response.ok) {
      return response
    }

    if (response.status >= 500 && retries > 0) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      return fetchWithRetry(url, options, retries - 1)
    }

    const body = await response.json().catch(() => null)
    const detail = body?.detail || body?.message || ''
    throw new Error(friendlyMessage(detail || `HTTP ${response.status}: ${response.statusText}`))
  } catch (error) {
    if (retries > 0 && error instanceof Error && !error.message.includes('denied') && !error.message.includes('expired') && !error.message.includes('Something went wrong')) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      return fetchWithRetry(url, options, retries - 1)
    }
    if (error instanceof Error) {
      throw new Error(friendlyMessage(error.message))
    }
    throw new Error('Something went wrong. Please try again.')
  }
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

    const uploadResponse: UploadResponse = {
      success: true,
      fileId: '1',
      fileName: file.name,
      uploadedAt: new Date().toISOString(),
    }

    const parsedData: ResumeData = {
      fullName: profile.name || '',
      email: profile.email || '',
      phoneNumber: profile.phone || '',
      linkedinUrl: profile.linkedin || '',
      githubUrl: profile.github || '',
      portfolioUrl: profile.portfolio || '',
      targetRole: profile.target_role || '',
      professionalSummary: profile.summary || '',
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
        endYear: edu.year ? parseInt(edu.year) : undefined,
      })),
      projects: (profile.projects || []).map((proj: any) => ({
        name: proj.name || '',
        description: proj.description || '',
        technologies: proj.technologies || [],
      })),
      languages: (profile.languages || []).map((l: string) => ({ name: l, proficiency: 'professional' as const })),
      certifications: (profile.certifications || []).map((c: string) => ({ name: c, issuer: '' })),
      metadata: {
        uploadedAt: new Date().toISOString(),
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

export async function submitResume(data: ResumeData): Promise<SubmitResponse> {
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
        body: JSON.stringify({ profile }),
      }
    )

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(friendlyMessage(body.detail || body.message || 'Submission failed'))
    }

    const result = await response.json()
    return {
      success: result.success,
      resumeId: '',
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
    }
  } catch (error) {
    throw {
      code: 'GET_FAILED',
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve resume',
    } as ApiError
  }
}

export function convertFormDataToResume(formData: {
  fullName: string
  targetRole: string
  skills: string
  experience: string
}): ResumeData {
  return {
    fullName: formData.fullName,
    targetRole: formData.targetRole,
    skills: formData.skills
      .split(',')
      .map(skill => ({ name: skill.trim() }))
      .filter(skill => skill.name),
    experiences: formData.experience
      ? [{
        company: 'Recent Experience',
        position: formData.targetRole,
        description: formData.experience,
        isCurrent: true,
      }]
      : [],
    education: [],
    metadata: {
      uploadedAt: new Date().toISOString(),
    },
  }
}

export async function fetchDashboardStats() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.STATS}`,
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
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve stats',
    } as ApiError
  }
}

export async function fetchRecentActivity(days: number = 30) {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.RECENT_ACTIVITY}?days=${days}`,
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
  is_selected: boolean
  created_at: string
}

export async function fetchJobProfiles(): Promise<JobProfile[]> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.JOB_PROFILES}`,
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

export async function createJobProfile(payload: {
  role: string
  company?: string
  tech_stack: string[]
}): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.JOB_PROFILES}`,
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

export async function selectJobProfile(profileId: number): Promise<JobProfile> {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.JOB_PROFILES}/${profileId}/select`,
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

export async function startInterviewSession(mode: 'practice' | 'mock', type: string, jobProfileId?: number, jobId?: number) {
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
          job_profile_id: jobProfileId || null,
          job_id: jobId || null
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

export async function fetchAnalytics() {
  try {
    const response = await fetchWithRetry(
      `${API_CONFIG.BASE_URL}${API_ENDPOINTS.DASHBOARD.ANALYTICS}`,
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
      message: error instanceof Error ? friendlyMessage(error.message) : 'Failed to retrieve analytics',
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
      `${API_CONFIG.BASE_URL}/dashboard/support`,
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
      `${API_CONFIG.BASE_URL}/dashboard/support/submissions${query}`,
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
      `${API_CONFIG.BASE_URL}/dashboard/support/submissions/${submissionId}`,
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

export async function createPaymentSession(planType: string, provider: string = 'stripe', paymentMethod: string = 'card', sessions?: number) {
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

