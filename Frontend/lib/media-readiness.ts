"use client"

export type MediaReadinessResult =
  | { ok: true; peakRms: number; audioOutputReady: boolean }
  | { ok: false; message: string }

export function mediaCaptureErrorMessage(error: unknown, kind: "microphone" | "camera" | "media" = "media") {
  const name = error instanceof DOMException ? error.name : ""
  if (name === "NotAllowedError" || name === "SecurityError") {
    return `${kind === "media" ? "Media" : kind[0].toUpperCase() + kind.slice(1)} access was denied. Allow it in browser and operating-system privacy settings, then retry.`
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return `The ${kind} could not be opened. It may be in use by another application or blocked by the operating system.`
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return `No usable ${kind} device was found.`
  }
  if (name === "OverconstrainedError") {
    return `The selected ${kind} does not support the required capture settings.`
  }
  return `The ${kind} readiness check failed. Reconnect the device and retry.`
}

export async function verifyAudioOutputReadiness(): Promise<{ ok: true } | { ok: false; message: string }> {
  const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AudioContextCtor) return { ok: false, message: "This browser cannot verify audio playback." }
  const context = new AudioContextCtor()
  try {
    await context.resume()
    return context.state === "running"
      ? { ok: true }
      : { ok: false, message: "Audio playback is blocked. Allow sound for this site, then retry." }
  } finally {
    await context.close().catch(() => undefined)
  }
}

export async function verifyMediaReadiness(
  stream: MediaStream,
  options: { requireAudio: boolean; requireVideo: boolean; sampleMs?: number },
): Promise<MediaReadinessResult> {
  const audioTracks = stream.getAudioTracks()
  const videoTracks = stream.getVideoTracks()
  if (options.requireAudio && !audioTracks.some((track) => track.readyState === "live" && track.enabled && !track.muted)) {
    return { ok: false, message: "The microphone did not produce a live, unmuted audio track." }
  }
  if (options.requireVideo && !videoTracks.some((track) => track.readyState === "live" && track.enabled)) {
    return { ok: false, message: "The camera did not produce a live video track." }
  }

  let peakRms = 0
  let audioOutputReady = !options.requireAudio
  if (options.requireAudio) {
    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextCtor) {
      return { ok: false, message: "This browser cannot measure microphone input or verify audio playback." }
    }
    const context = new AudioContextCtor()
    try {
      await context.resume()
      audioOutputReady = context.state === "running"
      const analyser = context.createAnalyser()
      analyser.fftSize = 1024
      const source = context.createMediaStreamSource(new MediaStream(audioTracks))
      source.connect(analyser)
      const samples = new Float32Array(analyser.fftSize)
      const deadline = performance.now() + Math.max(600, options.sampleMs ?? 1400)
      while (performance.now() < deadline) {
        analyser.getFloatTimeDomainData(samples)
        let sum = 0
        for (const sample of samples) sum += sample * sample
        peakRms = Math.max(peakRms, Math.sqrt(sum / samples.length))
        await new Promise((resolve) => setTimeout(resolve, 60))
      }
      source.disconnect()
      analyser.disconnect()
    } finally {
      await context.close().catch(() => undefined)
    }
    if (!audioOutputReady) {
      return { ok: false, message: "Audio playback is blocked. Allow sound for this site, then retry." }
    }
    // Silence at startup is normal: the candidate has not been asked a
    // question yet. A live, enabled, unmuted track is sufficient here; the
    // interview VAD continues measuring real speech after the room opens.
  }

  const devices = await navigator.mediaDevices.enumerateDevices().catch(() => [])
  if (options.requireAudio && !devices.some((device) => device.kind === "audioinput")) {
    return { ok: false, message: "No microphone is available to the browser." }
  }
  if (options.requireVideo && !devices.some((device) => device.kind === "videoinput")) {
    return { ok: false, message: "No camera is available to the browser." }
  }
  return { ok: true, peakRms, audioOutputReady }
}
