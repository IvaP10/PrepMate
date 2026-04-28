
export interface Skill {
  name: string
  level?: 'beginner' | 'intermediate' | 'advanced' | 'expert'
  yearsOfExperience?: number
}

export interface Education {
  institution: string
  degree: string
  field: string
  startYear?: number
  endYear?: number
  gpa?: number
  description?: string
}

export interface Experience {
  company: string
  position: string
  startDate?: string
  endDate?: string
  isCurrent?: boolean
  description?: string
  achievements?: string[]
}

export interface Project {
  name: string
  description: string
  url?: string
  technologies?: string[]
  startDate?: string
  endDate?: string
}

export interface ResumeData {
  fullName: string
  email?: string
  phoneNumber?: string
  location?: string
  linkedinUrl?: string
  githubUrl?: string
  portfolioUrl?: string

  targetRole: string
  professionalSummary?: string

  experiences: Experience[]
  education: Education[]

  skills: Skill[]
  languages?: {
    name: string
    proficiency: 'elementary' | 'limited' | 'professional' | 'full'
  }[]

  projects?: Project[]
  certifications?: {
    name: string
    issuer: string
    dateObtained?: string
    expiryDate?: string
  }[]

  summary?: string
  metadata?: {
    uploadedAt: string
    parsedAt?: string
    lastModifiedAt?: string
    userId?: string
  }
}

export interface VerifyFormData {
  fullName: string
  targetRole: string
  skills: string
  experience: string
}

export interface ParsedResumeResponse {
  success: boolean
  data: ResumeData
  warnings?: string[]
  errors?: string[]
}

export interface UploadResponse {
  success: boolean
  fileId: string
  fileName: string
  filePath?: string
  uploadedAt: string
}

export interface SubmitResponse {
  success: boolean
  resumeId: string
  message: string
  userProfile?: {
    id: string
    fullName: string
    targetRole: string
  }
}

export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown>
}
