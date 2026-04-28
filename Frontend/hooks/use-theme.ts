"use client"

import { useState, useEffect, useCallback } from "react"

type Theme = "light" | "dark"

const STORAGE_KEY = "interai-theme"

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("dark")

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
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

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    applyTheme(t, true)
    try {
      localStorage.setItem(STORAGE_KEY, t)
    } catch {}
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "dark" ? "light" : "dark"
      applyTheme(next, true)
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {}
      return next
    })
  }, [])

  return { theme, setTheme, toggleTheme }
}

function applyTheme(theme: Theme, animate = false) {
  const root = document.documentElement

  if (animate) {
    root.classList.add("theme-transition")
  }

  if (theme === "dark") {
    root.classList.add("dark")
  } else {
    root.classList.remove("dark")
  }

  if (animate) {
    setTimeout(() => {
      root.classList.remove("theme-transition")
    }, 550)
  }
}
