"use client"

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"

export interface SlidingSegmentOption<T extends string> {
  value: T
  label: string
  icon?: ReactNode
  disabled?: boolean
}

interface SlidingSegmentControlProps<T extends string> {
  options: SlidingSegmentOption<T>[]
  value: T
  onValueChange: (value: T) => void
  ariaLabel: string
  className?: string
  buttonClassName?: string
  shape?: "rounded" | "pill"
  wrap?: boolean
}

const SLIDE_MS = 176
const SLIDE_EASE = "cubic-bezier(0.33, 0.82, 0.28, 1)"

export function SlidingSegmentControl<T extends string>({
  options,
  value,
  onValueChange,
  ariaLabel,
  className,
  buttonClassName,
  shape = "rounded",
  wrap = false,
}: SlidingSegmentControlProps<T>) {
  const radiusClass = shape === "pill" ? "rounded-full" : "rounded-md"
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef(new Map<string, HTMLButtonElement>())
  const [activeRect, setActiveRect] = useState({ x: 4, y: 4, width: 0, height: 0 })
  const [isMoving, setIsMoving] = useState(false)
  const prevValueRef = useRef(value)

  useEffect(() => {
    if (prevValueRef.current === value) return
    prevValueRef.current = value
    setIsMoving(true)
    const timer = window.setTimeout(() => setIsMoving(false), SLIDE_MS)
    return () => window.clearTimeout(timer)
  }, [value])

  const measure = useCallback(() => {
    const container = containerRef.current
    const activeItem = itemRefs.current.get(value)
    if (!container || !activeItem) return

    const containerRect = container.getBoundingClientRect()
    const itemRect = activeItem.getBoundingClientRect()
    setActiveRect({
      x: itemRect.left - containerRect.left + container.scrollLeft,
      y: itemRect.top - containerRect.top + container.scrollTop,
      width: itemRect.width,
      height: itemRect.height,
    })
  }, [value])

  useLayoutEffect(() => {
    measure()
    const frame = window.requestAnimationFrame(measure)
    const container = containerRef.current
    if (!container) return () => window.cancelAnimationFrame(frame)

    const resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(container)
    itemRefs.current.forEach((item) => resizeObserver.observe(item))
    window.addEventListener("resize", measure)

    return () => {
      window.cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      window.removeEventListener("resize", measure)
    }
  }, [measure, options])

  return (
    <div
      ref={containerRef}
      role="group"
      aria-label={ariaLabel}
      onScroll={measure}
      className={cn(
        "relative flex max-w-full items-stretch gap-1 rounded-lg border border-border/50 bg-secondary/20 p-1",
        wrap ? "flex-wrap overflow-visible" : "overflow-x-auto iv-hide-scrollbar",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute left-0 top-0 overflow-hidden border border-primary/30 bg-primary/10 shadow-[0_6px_18px_rgba(79,70,229,0.12)] will-change-[transform,width,height] dark:border-primary/40 dark:bg-primary/18 dark:shadow-[0_0_24px_rgba(129,140,248,0.14)]",
          "backdrop-blur-md transition-[transform,width,box-shadow,background-color,backdrop-filter]",
          isMoving && "border-primary/45 bg-primary/16 shadow-[0_10px_32px_rgba(79,70,229,0.22)] backdrop-blur-xl dark:bg-primary/24",
          radiusClass,
        )}
        style={{
          transform: `translate3d(${activeRect.x}px, ${activeRect.y}px, 0)`,
          width: activeRect.width,
          height: activeRect.height,
          opacity: activeRect.width > 0 && activeRect.height > 0 ? 1 : 0,
          transitionDuration: isMoving ? `${SLIDE_MS}ms` : "0ms",
          transitionTimingFunction: SLIDE_EASE,
        }}
      >
        <span
          className={cn(
            "absolute inset-0 bg-gradient-to-b from-white/35 via-white/10 to-transparent dark:from-white/12 dark:via-white/5",
            "transition-opacity",
            radiusClass,
            isMoving ? "opacity-100" : "opacity-70",
          )}
          style={{
            transitionDuration: isMoving ? `${SLIDE_MS}ms` : "0ms",
            transitionTimingFunction: SLIDE_EASE,
          }}
        />
      </span>
      {options.map((option) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            ref={(node) => {
              if (node) itemRefs.current.set(option.value, node)
              else itemRefs.current.delete(option.value)
            }}
            type="button"
            disabled={option.disabled}
            aria-pressed={selected}
            onClick={() => onValueChange(option.value)}
            className={cn(
              "relative z-10 flex h-9 min-h-9 shrink-0 items-center justify-center gap-2 border border-transparent px-3 text-sm font-medium leading-none transition-colors",
              radiusClass,
              selected
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground",
              "disabled:pointer-events-none disabled:opacity-60",
              buttonClassName,
            )}
            style={{
              transitionDuration: `${SLIDE_MS}ms`,
              transitionTimingFunction: SLIDE_EASE,
            }}
          >
            {option.icon}
            <span className="whitespace-nowrap">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
