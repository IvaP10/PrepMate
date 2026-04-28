"use client"

import { useState, useRef, useCallback, useEffect } from "react"

interface WebRTCConfig {
  wsUrl: string
  onTrack?: (stream: MediaStream) => void
  onConnectionStateChange?: (state: RTCPeerConnectionState) => void
}

interface WebRTCState {
  connectionState: RTCPeerConnectionState | null
  remoteStream: MediaStream | null
  localStream: MediaStream | null
  isConnected: boolean
}

const ICE_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
]

export function useWebRTC(config: WebRTCConfig) {
  const [state, setState] = useState<WebRTCState>({
    connectionState: null,
    remoteStream: null,
    localStream: null,
    isConnected: false,
  })

  const pcRef = useRef<RTCPeerConnection | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const remoteStreamRef = useRef<MediaStream>(new MediaStream())

  const setupPeerConnection = useCallback(() => {
    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS })

    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "avatar_ice",
            candidate: event.candidate.toJSON(),
          })
        )
      }
    }

    pc.ontrack = (event) => {
      event.streams[0]?.getTracks().forEach((track) => {
        remoteStreamRef.current.addTrack(track)
      })
      setState((prev) => ({
        ...prev,
        remoteStream: remoteStreamRef.current,
      }))
      config.onTrack?.(remoteStreamRef.current)
    }

    pc.onconnectionstatechange = () => {
      const newState = pc.connectionState
      setState((prev) => ({
        ...prev,
        connectionState: newState,
        isConnected: newState === "connected",
      }))
      config.onConnectionStateChange?.(newState)
    }

    pcRef.current = pc
    return pc
  }, [config])

  const handleAvatarOffer = useCallback(
    async (sdpOffer: string, iceServers?: RTCIceServer[]) => {
      const pc = pcRef.current || setupPeerConnection()

      if (iceServers?.length) {
        const newPc = new RTCPeerConnection({
          iceServers: [...ICE_SERVERS, ...iceServers],
        })
        newPc.onicecandidate = pc.onicecandidate
        newPc.ontrack = pc.ontrack
        newPc.onconnectionstatechange = pc.onconnectionstatechange
        pcRef.current = newPc
      }

      const activePc = pcRef.current!
      await activePc.setRemoteDescription(
        new RTCSessionDescription({ type: "offer", sdp: sdpOffer })
      )
      const answer = await activePc.createAnswer()
      await activePc.setLocalDescription(answer)

      return answer.sdp
    },
    [setupPeerConnection]
  )

  const setupLocalMedia = useCallback(
    async (constraints: MediaStreamConstraints = { video: true, audio: true }) => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia(constraints)
        setState((prev) => ({ ...prev, localStream: stream }))

        if (pcRef.current) {
          stream.getTracks().forEach((track) => {
            pcRef.current!.addTrack(track, stream)
          })
        }

        return stream
      } catch (err) {
        console.error("Failed to get local media:", err)
        return null
      }
    },
    []
  )

  const cleanup = useCallback(() => {
    if (pcRef.current) {
      pcRef.current.close()
      pcRef.current = null
    }
    state.localStream?.getTracks().forEach((t) => t.stop())
    remoteStreamRef.current = new MediaStream()
    setState({
      connectionState: null,
      remoteStream: null,
      localStream: null,
      isConnected: false,
    })
  }, [state.localStream])

  useEffect(() => {
    return () => {
      cleanup()
    }
  }, [])

  return {
    ...state,
    peerConnection: pcRef.current,
    handleAvatarOffer,
    setupLocalMedia,
    setupPeerConnection,
    cleanup,
  }
}
