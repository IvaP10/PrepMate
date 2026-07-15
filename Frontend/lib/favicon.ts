export const FAVICON = {
  light: "/images/light.svg",
  dark: "/images/logo-dark.svg",
} as const

export type FaviconTheme = keyof typeof FAVICON

export function applyFavicon(theme: FaviconTheme) {
  if (typeof document === "undefined") return
  const href = FAVICON[theme]
  const selector = 'link[rel="icon"][data-theme-aware]'
  let link = document.querySelector<HTMLLinkElement>(selector)
  if (!link) {
    link =
      document.querySelector<HTMLLinkElement>('link[rel="icon"]') ??
      document.createElement("link")
    link.rel = "icon"
    link.type = "image/svg+xml"
    if (!link.isConnected) document.head.appendChild(link)
  }
  link.setAttribute("data-theme-aware", "true")
  if (!link.href.endsWith(href)) {
    link.href = href
  }
}
