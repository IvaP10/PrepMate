"use client"

import { useState, useEffect, useLayoutEffect, useCallback, useRef } from "react"
import { flushSync } from "react-dom"
import { applyFavicon } from "@/lib/favicon"
import { safeStorageGet, safeStorageSet } from "@/lib/safe-storage"

type Theme = "light" | "dark"

const STORAGE_KEY = "interai-theme"
const THEME_TRANSITION_MS = 700

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("dark")
  const transitionFrameRef = useRef<number | undefined>(undefined)
  const transitionTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

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

  useEffect(() => () => {
    if (transitionFrameRef.current !== undefined) cancelAnimationFrame(transitionFrameRef.current)
    if (transitionTimeoutRef.current !== undefined) clearTimeout(transitionTimeoutRef.current)
    document.documentElement.classList.remove("theme-transitioning")
  }, [])

  const transitionToTheme = useCallback((next: Theme) => {
    const root = document.documentElement
    if (transitionFrameRef.current !== undefined) cancelAnimationFrame(transitionFrameRef.current)
    if (transitionTimeoutRef.current !== undefined) clearTimeout(transitionTimeoutRef.current)

    root.classList.add("theme-transitioning")
    void getComputedStyle(document.body).transitionDuration

    transitionFrameRef.current = requestAnimationFrame(() => {
      transitionFrameRef.current = requestAnimationFrame(() => {
        applyTheme(next, true)
        flushSync(() => setThemeState(next))
        safeStorageSet("local", STORAGE_KEY, next)
        transitionFrameRef.current = undefined
        transitionTimeoutRef.current = setTimeout(() => {
          root.classList.remove("theme-transitioning")
          transitionTimeoutRef.current = undefined
        }, THEME_TRANSITION_MS + 40)
      })
    })
  }, [])

  const setTheme = useCallback((next: Theme) => {
    transitionToTheme(next)
  }, [transitionToTheme])

  const toggleTheme = useCallback(() => {
    const current = document.documentElement.classList.contains("dark") ? "dark" : "light"
    transitionToTheme(current === "dark" ? "light" : "dark")
  }, [transitionToTheme])

  return { theme, setTheme, toggleTheme }
}

function applyTheme(theme: Theme, transitionPrepared = false) {
  const root = document.documentElement
  if (transitionPrepared && !root.classList.contains("theme-transitioning")) return

  if (theme === "dark") {
    root.classList.remove("light")
    root.classList.add("dark")
  } else {
    root.classList.remove("dark")
    root.classList.add("light")
  }
  applyFavicon(theme)
}
