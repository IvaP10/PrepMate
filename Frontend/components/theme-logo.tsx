"use client"
import { memo } from "react"

interface ThemeLogoProps {
  size?: number
  className?: string
}

export const ThemeLogo = memo(function ThemeLogo({ size = 36, className = "" }: ThemeLogoProps) {
  const renderedSize = Math.round(size * 0.85)
  const containerWidth = renderedSize
  const containerHeight = renderedSize
  return (
    <span className={`relative inline-flex items-center justify-center ${className}`} style={{ width: containerWidth, height: containerHeight }}>
      <img
        src="/images/light.svg"
        alt="PrepMate logo"
        width={containerWidth}
        height={containerHeight}
        style={{ width: containerWidth, height: containerHeight }}
        className="object-contain dark:hidden"
      />
      <img
        src="/images/logo-dark.svg"
        alt="PrepMate logo"
        width={containerWidth}
        height={containerHeight}
        style={{ width: containerWidth, height: containerHeight }}
        className="hidden object-contain dark:block"
      />
    </span>
  )
})
