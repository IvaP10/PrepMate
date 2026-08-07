'use client'

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'
import type { ResumeData } from '@/types/resume'
import { getResume } from '@/lib/api'

interface ResumeContextType {
  resumeData: ResumeData | null
  isLoading: boolean
  error: string | null

  uploadedFileId: string | null
  uploadProgress: number

  setResumeData: (data: ResumeData) => void
  setUploadedFileId: (fileId: string) => void
  setUploadProgress: (progress: number) => void
  setError: (error: string | null) => void
  setLoading: (loading: boolean) => void

  isDataComplete: boolean
  justParsed: boolean
  setJustParsed: (val: boolean) => void

  reset: () => void
}

const ResumeContext = createContext<ResumeContextType | undefined>(undefined)

export function ResumeProvider({
  children,
  userId,
}: {
  children: React.ReactNode
  userId?: string | null
}) {
  const [resumeData, setResumeData] = useState<ResumeData | null>(null)
  const [uploadedFileId, setUploadedFileId] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isLoading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [justParsed, setJustParsed] = useState(false)

  useEffect(() => {
    if (!userId) {
      setResumeData(null)
      setLoading(false)
      setError(null)
      return
    }
    let cancelled = false

    const loadSavedResume = async () => {
      setLoading(true)
      setError(null)
      try {
        const saved = await getResume()
        if (!cancelled) {
          setResumeData(saved?.fullName ? saved : null)
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load the active resume.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadSavedResume()
    return () => { cancelled = true }
  }, [userId])

  const isDataComplete = Boolean(
    resumeData?.fullName &&
    resumeData?.skills?.length > 0
  )

  const reset = useCallback(() => {
    setResumeData(null)
    setUploadedFileId(null)
    setUploadProgress(0)
    setLoading(false)
    setError(null)
    setJustParsed(false)
  }, [])

  const value: ResumeContextType = {
    resumeData,
    isLoading,
    error,
    uploadedFileId,
    uploadProgress,
    setResumeData,
    setUploadedFileId,
    setUploadProgress,
    setError,
    setLoading,
    isDataComplete,
    justParsed,
    setJustParsed,
    reset,
  }

  return (
    <ResumeContext.Provider value={value}>
      {children}
    </ResumeContext.Provider>
  )
}

export function useResume() {
  const context = useContext(ResumeContext)
  if (!context) {
    throw new Error('useResume must be used within ResumeProvider')
  }
  return context
}
