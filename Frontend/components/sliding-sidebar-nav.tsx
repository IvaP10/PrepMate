"use client"

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
} from "react"
import { cn } from "@/lib/utils"

export interface SlidingSidebarNavItem<T extends string> {
  id: T
  label: string
  icon: ComponentType<{ className?: string }>
}

const SLIDE_MS = 176
const SLIDE_EASE = "cubic-bezier(0.33, 0.82, 0.28, 1)"

interface SlidingSidebarNavProps<T extends string> {
  items: SlidingSidebarNavItem<T>[]
  activeId: T
  onSelect: (id: T) => void
  ariaLabel: string
  collapsed?: boolean
  expanded?: boolean
  className?: string
  buttonClassName?: string
}

export function SlidingSidebarNav<T extends string>({
  items,
  activeId,
  onSelect,
  ariaLabel,
  collapsed = false,
  expanded = true,
  className,
  buttonClassName,
}: SlidingSidebarNavProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef(new Map<string, HTMLButtonElement>())
  const [activeRect, setActiveRect] = useState({ y: 4, height: 0 })
  const [isMoving, setIsMoving] = useState(false)
  const activeInGroup = items.some((item) => item.id === activeId)
  const activeIdRef = useRef(activeId)
  const activeInGroupRef = useRef(activeInGroup)
  activeIdRef.current = activeId
  activeInGroupRef.current = activeInGroup
  const prevActiveIdRef = useRef(activeId)

  const measure = useCallback(() => {
    const container = containerRef.current
    const activeItem = itemRefs.current.get(activeIdRef.current)
    if (!container || !activeItem || !activeInGroupRef.current) {
      setActiveRect((prev) => (prev.height === 0 ? prev : { ...prev, height: 0 }))
      return
    }

    const containerRect = container.getBoundingClientRect()
    const itemRect = activeItem.getBoundingClientRect()
    const nextY = itemRect.top - containerRect.top + container.scrollTop
    const nextHeight = itemRect.height
    setActiveRect((prev) => {
      if (Math.abs(prev.y - nextY) < 0.5 && Math.abs(prev.height - nextHeight) < 0.5) {
        return prev
      }
      return { y: nextY, height: nextHeight }
    })
  }, [])

  useEffect(() => {
    if (prevActiveIdRef.current === activeId) return
    prevActiveIdRef.current = activeId
    setIsMoving(true)
    let secondFrame: number | null = null
    let timer: number | null = null
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        measure()
        timer = window.setTimeout(() => setIsMoving(false), SLIDE_MS)
      })
    })
    return () => {
      window.cancelAnimationFrame(firstFrame)
      if (secondFrame != null) window.cancelAnimationFrame(secondFrame)
      if (timer != null) window.clearTimeout(timer)
    }
  }, [activeId, measure])

  const measureRafRef = useRef<number | null>(null)
  const scheduleMeasure = useCallback(() => {
    if (measureRafRef.current != null) return
    measureRafRef.current = window.requestAnimationFrame(() => {
      measureRafRef.current = null
      measure()
    })
  }, [measure])

  useLayoutEffect(() => {
    measure()
    const container = containerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver(scheduleMeasure)
    resizeObserver.observe(container)
    itemRefs.current.forEach((item) => resizeObserver.observe(item))

    return () => {
      if (measureRafRef.current != null) {
        window.cancelAnimationFrame(measureRafRef.current)
        measureRafRef.current = null
      }
      resizeObserver.disconnect()
    }
  }, [measure, scheduleMeasure, items])

  useLayoutEffect(() => {
    measure()
  }, [measure, collapsed, expanded])

  const showLabel = expanded && !collapsed
  const prevShowLabelRef = useRef(showLabel)
  const [labelTransitioning, setLabelTransitioning] = useState(false)

  useEffect(() => {
    if (prevShowLabelRef.current === showLabel) return
    prevShowLabelRef.current = showLabel
    setLabelTransitioning(true)
    const timer = window.setTimeout(() => setLabelTransitioning(false), 300)
    return () => window.clearTimeout(timer)
  }, [showLabel])

  return (
    <nav
      ref={containerRef}
      aria-label={ariaLabel}
      className={cn("relative flex flex-col gap-1.5 p-1", className)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute inset-x-1 top-0 overflow-hidden rounded-lg border border-primary/30 bg-primary/10 shadow-[0_6px_18px_rgba(79,70,229,0.12)] dark:border-primary/40 dark:bg-primary/18 dark:shadow-[0_0_24px_rgba(129,140,248,0.14)]",
          "backdrop-blur-md transition-[transform,height,box-shadow,background-color,backdrop-filter]",
          "motion-reduce:transition-none",
          isMoving &&
            "border-primary/45 bg-primary/16 shadow-[0_10px_32px_rgba(79,70,229,0.22)] backdrop-blur-xl dark:bg-primary/24",
        )}
        style={{
          transform: `translate3d(0, ${activeRect.y}px, 0)`,
          height: activeRect.height,
          opacity: activeInGroup && activeRect.height > 0 ? 1 : 0,
          transitionDuration: isMoving ? `${SLIDE_MS}ms` : "0ms",
          transitionTimingFunction: SLIDE_EASE,
        }}
      >
        <span
          className={cn(
            "absolute inset-0 rounded-lg bg-gradient-to-b from-white/35 via-white/10 to-transparent dark:from-white/12 dark:via-white/5",
            "transition-opacity",
            isMoving ? "opacity-100" : "opacity-70",
          )}
          style={{
            transitionDuration: isMoving ? `${SLIDE_MS}ms` : "0ms",
            transitionTimingFunction: SLIDE_EASE,
          }}
        />
      </span>
      {items.map((item) => {
        const selected = activeId === item.id
        const Icon = item.icon
        return (
          <button
            key={item.id}
            ref={(node) => {
              if (node) itemRefs.current.set(item.id, node)
              else itemRefs.current.delete(item.id)
            }}
            type="button"
            title={collapsed ? item.label : undefined}
            aria-current={selected ? "page" : undefined}
            onClick={() => onSelect(item.id)}
            className={cn(
              "relative z-10 flex w-full items-center rounded-lg border border-transparent text-sm font-medium transition-[color,background-color]",
              showLabel ? "h-10 pl-[10px] pr-3" : "h-10 justify-start pl-[14px] pr-3",
              selected
                ? "text-foreground"
                : "text-muted-foreground hover:bg-primary/[0.04] hover:text-foreground dark:hover:bg-primary/[0.07]",
              buttonClassName,
            )}
            style={{
              transitionDuration: `${SLIDE_MS}ms`,
              transitionTimingFunction: SLIDE_EASE,
            }}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span
              className={cn(
                "overflow-hidden whitespace-nowrap",
                labelTransitioning && "transition-[transform,margin,max-width] duration-300 ease-out",
                showLabel
                  ? "ml-3 max-w-[150px] translate-x-0"
                  : "pointer-events-none ml-0 max-w-0 -translate-x-2",
              )}
            >
              {item.label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
