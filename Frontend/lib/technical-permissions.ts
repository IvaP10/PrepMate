"use client"

import { mediaCaptureErrorMessage, verifyMediaReadiness } from "@/lib/media-readiness"

export type TechnicalPermissionState = {
  fullscreenAttempted: boolean
  fullscreenActive: boolean
  fullscreenReady: boolean
  screenShareReady: boolean
  screenShareSurface?: string | null
  cameraReady: boolean
  microphoneReady: boolean
  ready: boolean
}

export type TechnicalPermissionResult =
  | { ok: true; state: TechnicalPermissionState }
  | { ok: false; reason: "unsupported" | "fullscreen" | "screen-share" | "camera" | "microphone"; message: string }

type PermissionListener = (state: TechnicalPermissionState) => void

type PermissionRuntime = {
  displayStream: MediaStream | null
  displaySurface: string | null
  cameraStream: MediaStream | null
  microphoneStream: MediaStream | null
  fullscreenListenerAttached: boolean
  fullscreenRequestAttempted: boolean
  permissionsReleased: boolean
  preflightDone: boolean
}

const runtimeKey = "__prepmateTechnicalPermissionRuntime" as const
const runtimeHost = globalThis as typeof globalThis & { [runtimeKey]?: PermissionRuntime }
const runtime = runtimeHost[runtimeKey] ||= {
  displayStream: null,
  displaySurface: null,
  cameraStream: null,
  microphoneStream: null,
  fullscreenListenerAttached: false,
  fullscreenRequestAttempted: false,
  permissionsReleased: false,
  preflightDone: false,
}
const listeners = new Set<PermissionListener>()
const MEDIA_PERMISSION_TIMEOUT_MS = 60_000

async function requestMediaWithTimeout(
  request: Promise<MediaStream>,
  timeoutMessage: string,
): Promise<MediaStream> {
  let timedOut = false
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true
      reject(new Error(timeoutMessage))
    }, MEDIA_PERMISSION_TIMEOUT_MS)
  })
  void request.then((stream) => {
    if (timedOut) stream.getTracks().forEach((track) => track.stop())
  }).catch(() => undefined)
  try {
    return await Promise.race([request, timeout])
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }
}

function isBrowser() {
  return typeof window !== "undefined" && typeof document !== "undefined"
}

function hasLiveDisplayStream() {
  if (!runtime.displayStream) return false
  const tracks = runtime.displayStream.getVideoTracks()
  return tracks.length > 0 && tracks.some((track) => track.readyState === "live")
}

function hasLiveCameraStream() {
  if (!runtime.cameraStream) return false
  const tracks = runtime.cameraStream.getVideoTracks()
  return tracks.length > 0 && tracks.some((track) => track.readyState === "live")
}

function hasLiveMicrophoneStream() {
  if (!runtime.microphoneStream) return false
  const tracks = runtime.microphoneStream.getAudioTracks()
  return tracks.length > 0 && tracks.some((track) => track.readyState === "live" && track.enabled && !track.muted)
}

function pruneEndedStreams() {
  if (runtime.displayStream && !hasLiveDisplayStream()) {
    runtime.displayStream = null
    runtime.displaySurface = null
  }
  if (runtime.cameraStream && !hasLiveCameraStream()) {
    runtime.cameraStream = null
  }
  if (runtime.microphoneStream && !hasLiveMicrophoneStream()) {
    runtime.microphoneStream = null
  }
}

function computeState(): TechnicalPermissionState {
  if (!isBrowser()) {
    return {
      fullscreenAttempted: false,
      fullscreenActive: false,
      fullscreenReady: false,
      screenShareReady: false,
      screenShareSurface: null,
      cameraReady: false,
      microphoneReady: false,
      ready: true,
    }
  }

  pruneEndedStreams()
  const fullscreenActive = !document.fullscreenEnabled || Boolean(document.fullscreenElement)
  const fullscreenAttempted = !document.fullscreenEnabled || runtime.fullscreenRequestAttempted
  const fullscreenReady = fullscreenActive
  const screenShareReady = hasLiveDisplayStream()
  const cameraReady = hasLiveCameraStream()
  const microphoneReady = hasLiveMicrophoneStream()

  return {
    fullscreenAttempted,
    fullscreenActive,
    fullscreenReady,
    screenShareReady,
    screenShareSurface: runtime.displaySurface,
    cameraReady,
    microphoneReady,
    // Technical answers are usable with typed input and no media capture.
    // Camera, microphone, and screen sharing are optional coaching tools and
    // become ready only when the user explicitly enables them.
    ready: true,
  }
}

function emitPermissionState() {
  const state = computeState()
  listeners.forEach((listener) => listener(state))
}

function attachFullscreenListener() {
  if (!isBrowser() || runtime.fullscreenListenerAttached) return
  document.addEventListener("fullscreenchange", emitPermissionState)
  runtime.fullscreenListenerAttached = true
}

function holdDisplayStream(stream: MediaStream) {
  runtime.displayStream = stream
  const settings = stream.getVideoTracks()[0]?.getSettings?.() as MediaTrackSettings & { displaySurface?: string }
  runtime.displaySurface = settings?.displaySurface || null
  stream.getTracks().forEach((track) => {
    track.addEventListener(
      "ended",
      () => {
        if (runtime.displayStream === stream) {
          runtime.displayStream = null
          runtime.displaySurface = null
        }
        emitPermissionState()
      },
      { once: true }
    )
  })
  emitPermissionState()
}

function holdCameraStream(stream: MediaStream) {
  runtime.cameraStream = stream
  stream.getTracks().forEach((track) => {
    track.addEventListener(
      "ended",
      () => {
        if (runtime.cameraStream === stream) runtime.cameraStream = null
        emitPermissionState()
      },
      { once: true }
    )
  })
  emitPermissionState()
}

function holdMicrophoneStream(stream: MediaStream) {
  runtime.microphoneStream = stream
  stream.getTracks().forEach((track) => {
    track.addEventListener("ended", () => {
      if (runtime.microphoneStream === stream) runtime.microphoneStream = null
      emitPermissionState()
    }, { once: true })
  })
  emitPermissionState()
}

export function getTechnicalPermissionState() {
  attachFullscreenListener()
  return computeState()
}

export function getTechnicalCameraStream() {
  return runtime.cameraStream
}

export function getTechnicalMicrophoneStream() {
  return runtime.microphoneStream
}

export function subscribeTechnicalPermissionState(listener: PermissionListener) {
  attachFullscreenListener()
  listeners.add(listener)
  listener(computeState())
  return () => {
    listeners.delete(listener)
  }
}

export async function requestTechnicalScreenShare(): Promise<TechnicalPermissionResult> {
  if (!isBrowser() || !navigator.mediaDevices?.getDisplayMedia) {
    return {
      ok: false,
      reason: "unsupported",
      message: "This browser cannot request screen sharing for technical rounds.",
    }
  }

  attachFullscreenListener()

  if (!hasLiveDisplayStream()) {
    try {
      const stream = await requestMediaWithTimeout(
        navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: false,
        }),
        "Screen coaching timed out. Try again within one minute.",
      )
      runtime.permissionsReleased = false
      holdDisplayStream(stream)
    } catch (error) {
      emitPermissionState()
      return {
        ok: false,
        reason: "screen-share",
        message: error instanceof Error && /timed out/i.test(error.message)
          ? error.message
          : "Screen coaching was not enabled. You can continue without it.",
      }
    }
  }

  return { ok: true, state: computeState() }
}

export async function requestTechnicalFullscreen(): Promise<TechnicalPermissionResult> {
  if (!isBrowser()) {
    return { ok: false, reason: "unsupported", message: "Fullscreen is not available in this environment." }
  }

  attachFullscreenListener()

  if (document.fullscreenEnabled && !document.fullscreenElement) {
    try {
      await document.documentElement.requestFullscreen()
      runtime.fullscreenRequestAttempted = true
    } catch {
      emitPermissionState()
      return {
        ok: false,
        reason: "fullscreen",
        message: "Fullscreen is required before the technical round can start.",
      }
    }
  }

  return { ok: true, state: computeState() }
}

export async function requestTechnicalCamera(): Promise<TechnicalPermissionResult> {
  if (!isBrowser() || !navigator.mediaDevices?.getUserMedia) {
    return {
      ok: false,
      reason: "unsupported",
      message: "Camera access is not available in this browser.",
    }
  }

  if (!hasLiveCameraStream()) {
    try {
      const stream = await requestMediaWithTimeout(
        navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        }),
        "Camera permission timed out. Try again and allow camera access within one minute.",
      )
      holdCameraStream(stream)
    } catch (error) {
      emitPermissionState()
      return {
        ok: false,
        reason: "camera",
        message: error instanceof Error && /timed out/i.test(error.message)
          ? error.message
          : "Camera coaching is unavailable. Continue without it or try again.",
      }
    }
  }

  return { ok: true, state: computeState() }
}

export async function requestTechnicalMicrophone(): Promise<TechnicalPermissionResult> {
  if (!isBrowser() || !navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "unsupported", message: "Microphone access is not available in this browser." }
  }
  if (!hasLiveMicrophoneStream()) {
    try {
      const stream = await requestMediaWithTimeout(
        navigator.mediaDevices.getUserMedia({ audio: true, video: false }),
        "Microphone permission timed out. Try again and allow microphone access within one minute.",
      )
      const readiness = await verifyMediaReadiness(stream, { requireAudio: true, requireVideo: false })
      if (!readiness.ok) {
        stream.getTracks().forEach((track) => track.stop())
        return { ok: false, reason: "microphone", message: readiness.message }
      }
      holdMicrophoneStream(stream)
  } catch (error) {
    emitPermissionState()
    return {
      ok: false,
      reason: "microphone",
      message: error instanceof Error && /timed out/i.test(error.message)
        ? error.message
        : mediaCaptureErrorMessage(error, "microphone"),
    }
    }
  }
  return { ok: true, state: computeState() }
}

export async function requestTechnicalMedia(): Promise<TechnicalPermissionResult> {
  if (!isBrowser() || !navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "unsupported", message: "Camera and microphone access are not available in this browser." }
  }
  if (hasLiveCameraStream() && hasLiveMicrophoneStream()) {
    return { ok: true, state: computeState() }
  }
  try {
    const stream = await requestMediaWithTimeout(
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: true,
      }),
      "Camera and microphone permission timed out. Try again and allow access within one minute.",
    )
    const readiness = await verifyMediaReadiness(stream, { requireAudio: true, requireVideo: true })
    if (!readiness.ok) {
      stream.getTracks().forEach((track) => track.stop())
      return { ok: false, reason: "camera", message: readiness.message }
    }
    const cameraTrack = stream.getVideoTracks()[0]
    const microphoneTrack = stream.getAudioTracks()[0]
    if (!cameraTrack || !microphoneTrack) {
      stream.getTracks().forEach((track) => track.stop())
      return { ok: false, reason: "camera", message: "Allow both camera and microphone access to continue." }
    }
    holdCameraStream(new MediaStream([cameraTrack]))
    holdMicrophoneStream(new MediaStream([microphoneTrack]))
    return { ok: true, state: computeState() }
  } catch (error) {
    emitPermissionState()
    return {
      ok: false,
      reason: "camera",
      message: error instanceof Error && /timed out/i.test(error.message)
        ? error.message
        : mediaCaptureErrorMessage(error, "media"),
    }
  }
}

export async function requestTechnicalPermissions(): Promise<TechnicalPermissionResult> {
  // A typed technical round never requests media or fullscreen implicitly.
  // Individual coaching controls call the specific permission function only
  // after the user chooses that feature.
  return { ok: true, state: computeState() }
}

export function stopTechnicalScreenShare() {
  if (runtime.displayStream) {
    runtime.displayStream.getTracks().forEach((track) => track.stop())
    runtime.displayStream = null
    runtime.displaySurface = null
  }
  emitPermissionState()
}

export function stopTechnicalCamera() {
  if (runtime.cameraStream) {
    runtime.cameraStream.getTracks().forEach((track) => track.stop())
    runtime.cameraStream = null
  }
  emitPermissionState()
}

export function stopTechnicalMicrophone() {
  if (runtime.microphoneStream) {
    runtime.microphoneStream.getTracks().forEach((track) => track.stop())
    runtime.microphoneStream = null
  }
  emitPermissionState()
}

export async function releaseTechnicalPermissions() {
  runtime.permissionsReleased = true
  runtime.preflightDone = false
  stopTechnicalScreenShare()
  stopTechnicalCamera()
  stopTechnicalMicrophone()
  runtime.fullscreenRequestAttempted = false
  if (isBrowser() && document.fullscreenElement) {
    await document.exitFullscreen().catch(() => undefined)
  }
  emitPermissionState()
}

// --- Preflight flag ---
// Signals that the preflight dialog already acquired all permissions.
// The technical page reads (and clears) this flag to skip its own
// PermissionGate and avoid prompting for screen share a second time.
export function markPreflightCompleted() {
  runtime.preflightDone = true
  runtime.permissionsReleased = false
}

export function consumePreflightFlag(): boolean {
  if (runtime.preflightDone) {
    runtime.preflightDone = false
    return true
  }
  return false
}
