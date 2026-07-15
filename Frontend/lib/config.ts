const DEFAULT_API_BASE_URL = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000/api'

export const API_CONFIG = {
  BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL,
  TIMEOUT: 30000,
  RETRY_ATTEMPTS: 3,
} as const

/** Resume upload only — must match backend RESUME_MAX_FILE_SIZE_MB (default 4). */
export const RESUME_MAX_FILE_BYTES = 4 * 1024 * 1024

export const API_ENDPOINTS = {
  AUTH: {
    SIGNUP: '/auth/signup',
    LOGIN: '/auth/login',
    GOOGLE: '/auth/google',
    VERIFY: '/auth/verify',
    REFRESH: '/auth/refresh',
    FORGOT_PASSWORD: '/auth/forgot-password',
    RESET_PASSWORD: '/auth/reset-password',
    CHANGE_PASSWORD: '/auth/change-password',
    DELETE_ACCOUNT: '/auth/delete-account',
    LOGOUT: '/auth/logout',
  },
  RESUME: {
    UPLOAD: '/pre-interview/upload-resume',
    VERSIONS: '/pre-interview/resumes',
    CONFIRM: '/pre-interview/confirm-profile',
    FORM: '/pre-interview/form',
    STATUS: '/pre-interview/profile-status',
    RESET: '/pre-interview/reset-profile',
  },
  INTERVIEW: {
    START: '/interview/start',
    BLUEPRINTS: '/interview/blueprints',
    REPORT: '/interview/report',
    STATUS: '/interview/status',
    ANALYSIS_STATUS: '/interview',
    CANCEL: '/interview/cancel',
    WS_TICKET: '/interview/ws-ticket',
  },
  ANALYSIS: {
    RECONCILE_PERFORMANCE: '/analysis/reconcile-performance',
  },
  WORKSPACE: {
    JOBS: '/workspace/jobs',
    JOB_PROFILES: '/workspace/job-profiles',
    INTERVIEW_PROFILE: '/workspace/interview-profile',
    RECENT_ACTIVITY: '/workspace/recent-activity',
    PERFORMANCE: '/workspace/performance',
    TECHNICAL_ROUNDS: '/workspace/technical-rounds',
    LEARNING: '/workspace/learning',
    EXERCISES: '/workspace/exercises',
    EXERCISE_ATTEMPT: '/workspace/exercises',
    EXERCISE_RUN: '/workspace/exercises',
  },
  PROFILE: {
    ME: '/profile/me',
    UPDATE: '/profile/update',
    UPDATE_ACCOUNT: '/profile/update-account',
    AVATAR: '/profile/avatar',
    EXPORT_DATA: '/profile/export-data',
    DELETE_SESSION_HISTORY: '/profile/session-history',
    NOTIFICATION_PREFS: '/profile/notification-prefs',
    STATISTICS: '/profile/statistics',
    HISTORY: '/profile/interview-history',
    ENTITLEMENTS: '/profile/entitlements',
  },
  PAYMENT: {
    CREATE_SUBSCRIPTION: '/payment/create-subscription',
    GET_SUBSCRIPTION: '/payment/subscription',
    VERIFY_RAZORPAY: '/payment/verify-razorpay',
    PRICING: '/payment/pricing',
    PLANS: '/payment/plans',
    TRANSACTIONS: '/payment/transactions',
  },
} as const
