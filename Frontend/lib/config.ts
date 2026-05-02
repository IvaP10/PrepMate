
export const API_CONFIG = {
  BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api',
  TIMEOUT: 120000,
  RETRY_ATTEMPTS: 3,
} as const

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
    CONFIRM: '/pre-interview/confirm-profile',
    FORM: '/pre-interview/form',
    STATUS: '/pre-interview/profile-status',
    RESET: '/pre-interview/reset-profile',
  },
  INTERVIEW: {
    START: '/interview/start',
    REPORT: '/interview/report',
    STATUS: '/interview/status',
    CANCEL: '/interview/cancel',
    WS_TICKET: '/interview/ws-ticket',
  },
  DASHBOARD: {
    STATS: '/dashboard/stats',
    JOBS: '/dashboard/jobs',
    JOB_PROFILES: '/dashboard/job-profiles',
    RECENT_ACTIVITY: '/dashboard/recent-activity',
    PERFORMANCE: '/dashboard/performance-trend',
    ANALYTICS: '/dashboard/analytics',
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
  },
  PAYMENT: {
    CREATE_SUBSCRIPTION: '/payment/create-subscription',
    GET_SUBSCRIPTION: '/payment/subscription',
    VERIFY_RAZORPAY: '/payment/verify-razorpay',
    PRICING: '/payment/pricing',
    TRANSACTIONS: '/payment/transactions',
  },
} as const
