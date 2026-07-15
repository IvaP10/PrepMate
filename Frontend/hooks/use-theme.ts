"use client"

import { useState, useEffect, useLayoutEffect, useCallback } from "react"
import { applyFavicon } from "@/lib/favicon"
import { safeStorageGet, safeStorageSet } from "@/lib/safe-storage"

type Theme = "light" | "dark"

const STORAGE_KEY = "interai-theme"
let themeTransitionTimeout: ReturnType<typeof setTimeout> | undefined

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("dark")

  useEffect(() => {
    try {
      const stored = safeStorageGet("local", STORAGE_KEY) as Theme | null
      if (stored === "light" || stored === "dark") {
        setThemeState(stored)
        applyTheme(stored)
      } else if (window.matchMedia("(prefers-color-scheme: light)").matches) {
        setThemeState("light")
        applyTheme("light")
      } else {
        applyTheme("dark")
      }
    } catch {
      applyTheme("dark")
    }
  }, [])

  useLayoutEffect(() => {
    applyTheme(theme)
  }, [theme])

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    applyTheme(t, true)
    safeStorageSet("local", STORAGE_KEY, t)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "dark" ? "light" : "dark"
      applyTheme(next, true)
      safeStorageSet("local", STORAGE_KEY, next)
      return next
    })
  }, [])

  return { theme, setTheme, toggleTheme }
}

function applyTheme(theme: Theme, animate = false) {
  const root = document.documentElement

  if (animate) {
    if (themeTransitionTimeout) {
      clearTimeout(themeTransitionTimeout)
    }
    root.classList.add("theme-transition")
    void root.offsetWidth
  }

  if (theme === "dark") {
    root.classList.remove("light")
    root.classList.add("dark")
  } else {
    root.classList.remove("dark")
    root.classList.add("light")
  }
  applyFavicon(theme)

  if (animate) {
    themeTransitionTimeout = setTimeout(() => {
      root.classList.remove("theme-transition")
      themeTransitionTimeout = undefined
    }, 950)
  }
}
