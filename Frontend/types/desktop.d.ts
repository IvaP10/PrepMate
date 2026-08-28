export {}

declare global {
  interface Window {
    prepmateDesktop?: {
      apiBaseUrl: string
      platform: string
      version: string
      openDataFolder?: () => Promise<{ success: boolean; error?: string }>
    }
  }
}
