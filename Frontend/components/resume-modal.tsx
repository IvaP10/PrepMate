"use client"
import { useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import {
  Upload,
  FileText,
  Check,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { uploadResume } from "@/lib/api"
import { useResume } from "@/context/resume-context"
import type { ResumeData } from "@/types/resume"
type ModalStep = "upload" | "parsing" | "verify"
interface ResumeModalProps {
  open: boolean
  onClose: () => void
}
function UploadStep({
  onUploadStart,
  onSkip,
  onError,
}: {
  onUploadStart: (file: File) => void
  onSkip: () => void
  onError: (error: string) => void
}) {
  const [isDragging, setIsDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const handleUpload = () => {
    if (!file) return
    onUploadStart(file)
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile && (droppedFile.type.includes('pdf') || droppedFile.type.includes('document'))) {
      setFile(droppedFile)
    } else {
      onError("Please upload a PDF or DOCX file")
    }
  }
  return (
    <>
      <DialogHeader>
        <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-xl bg-secondary ring-1 ring-border">
          <Upload className="h-5 w-5 text-muted-foreground" />
        </div>
        <DialogTitle className="text-xl font-bold text-foreground">
          {"Let's personalize your AI."}
        </DialogTitle>
        <DialogDescription className="text-muted-foreground">
          Upload your resume so we can tailor interview questions to your
          background and goals.
        </DialogDescription>
      </DialogHeader>
      <div
        className={`relative flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-12 transition-all duration-200 ${isDragging
          ? "border-primary bg-primary/5"
          : file
            ? "border-primary/40 bg-primary/5"
            : "border-border bg-secondary/30 hover:border-muted-foreground/30"
          }`}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        {file ? (
          <>
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
              <FileText className="h-7 w-7 text-primary" />
            </div>
            <div className="flex flex-col items-center gap-1">
              <p className="text-sm font-medium text-foreground">{file.name}</p>
              <p className="text-xs text-muted-foreground">Ready to upload</p>
            </div>
            <button
              type="button"
              onClick={() => setFile(null)}
              className="absolute top-3 right-3 rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
              aria-label="Remove file"
            >
              <X className="h-4 w-4" />
            </button>
          </>
        ) : (
          <>
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary ring-1 ring-border">
              <Upload className="h-7 w-7 text-muted-foreground" />
            </div>
            <div className="flex flex-col items-center gap-1">
              <p className="text-sm font-medium text-foreground">
                Drag & Drop Resume
              </p>
              <p className="text-xs text-muted-foreground">
                PDF or DOCX, up to 5MB
              </p>
            </div>
            <input
              type="file"
              accept=".pdf,.docx"
              className="absolute inset-0 cursor-pointer opacity-0"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) {
                  if (f.size > 5 * 1024 * 1024) {
                    onError("File size must be less than 5MB")
                  } else {
                    setFile(f)
                  }
                }
              }}
            />
          </>
        )}
      </div>
      <DialogFooter className="flex-row justify-between sm:justify-between">
        <Button
          variant="ghost"
          onClick={onSkip}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          {"I'll do this later"}
        </Button>
        <Button
          onClick={handleUpload}
          disabled={!file}
        >
          Upload & Parse
        </Button>
      </DialogFooter>
    </>
  )
}
const parsingSteps = [
  { label: "Reading Document" },
  { label: "Anonymizing PII" },
  { label: "Extracting Skills & Experience" },
]
function ParsingStep({
  onComplete,
  parsedData
}: {
  onComplete: () => void
  parsedData: ResumeData | null
}) {
  const [activeIndex, setActiveIndex] = useState(0)
  const [completedSteps, setCompletedSteps] = useState<number[]>([])
  const [progress, setProgress] = useState(0)

  // When real data arrives, instantly complete everything and exit
  useEffect(() => {
    if (!parsedData) return
    setProgress(100)
    setCompletedSteps([0, 1, 2])
    setActiveIndex(2)
    const t = setTimeout(() => onComplete(), 300)
    return () => clearTimeout(t)
  }, [parsedData]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fake progress animation while waiting
  useEffect(() => {
    const progressInterval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 90) return 90
        return prev + 3
      })
    }, 150)
    const timers = parsingSteps.map((_, i) =>
      setTimeout(() => {
        setCompletedSteps((prev) =>
          prev.includes(i) ? prev : [...prev, i]
        )
        if (i < parsingSteps.length - 1) setActiveIndex(i + 1)
      }, (i + 1) * 800)
    )
    return () => {
      clearInterval(progressInterval)
      timers.forEach(clearTimeout)
    }
  }, [])

  const allDone = completedSteps.length === parsingSteps.length
  return (
    <>
      <div className="flex flex-col items-center gap-8 py-4">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-secondary ring-1 ring-border">
          {allDone ? (
            <Check className="h-8 w-8 text-foreground" />
          ) : (
            <FileText className="h-7 w-7 text-muted-foreground" />
          )}
        </div>
        <div className="flex flex-col items-center gap-2 text-center">
          <h3 className="text-lg font-semibold tracking-tight text-foreground">
            {allDone ? "Profile ready" : "Reading your resume"}
          </h3>
          <p className="max-w-[280px] text-[13px] leading-relaxed text-muted-foreground">
            {allDone
              ? "Everything looks good. Wrapping up."
              : "Pulling out the details that matter — skills, experience, the works."}
          </p>
        </div>
        <div className="w-full space-y-0">
          {parsingSteps.map((step, i) => {
            const isDone = completedSteps.includes(i)
            const isActive = activeIndex === i && !isDone
            const isLast = i === parsingSteps.length - 1
            return (
              <div key={step.label} className="flex items-stretch gap-4">
                <div className="flex flex-col items-center">
                  <div
                    className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-all duration-500 ${
                      isDone
                        ? "bg-foreground"
                        : isActive
                          ? "bg-secondary ring-1 ring-border"
                          : "bg-border"
                    }`}
                  >
                    {isDone ? (
                      <Check className="h-3 w-3 text-background" />
                    ) : isActive ? (
                      <div className="h-2 w-2 rounded-full bg-muted-foreground animate-pulse" />
                    ) : (
                      <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                    )}
                  </div>
                  {!isLast && (
                    <div className="relative w-px flex-1 min-h-[24px]">
                      <div className="absolute inset-0 bg-border" />
                      <div
                        className="absolute inset-x-0 top-0 bg-foreground/30 transition-all duration-700 ease-out"
                        style={{ height: isDone ? "100%" : "0%" }}
                      />
                    </div>
                  )}
                </div>
                <div className={`pb-6 pt-0.5 transition-all duration-500 ${isLast ? "pb-0" : ""}`}>
                  <span
                    className={`text-sm transition-colors duration-500 ${
                      isDone
                        ? "font-medium text-foreground"
                        : isActive
                          ? "font-medium text-foreground"
                          : "text-muted-foreground/60"
                    }`}
                  >
                    {step.label}
                  </span>
                  {isActive && (
                    <span className="ml-1.5 inline-block text-xs text-muted-foreground">
                      {Math.min(progress, 95)}%
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}


export function ResumeModal({ open, onClose }: ResumeModalProps) {
  const [modalStep, setModalStep] = useState<ModalStep>("upload")
  const [parsedData, setParsedData] = useState<ResumeData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { setResumeData: setContextResumeData, setJustParsed } = useResume()
  const handleUploadStart = async (file: File) => {
    setModalStep("parsing")
    setError(null)
    setParsedData(null)
    try {
      const { parsedData: result } = await uploadResume(file)
      setParsedData(result)
    } catch (err) {
      const error = err as any
      handleError(error.message || "Failed to upload resume")
      setModalStep("upload")
    }
  }
  const handleParsingComplete = () => {
    if (!parsedData) return
    // Set context data and flag so dashboard opens directly in edit mode
    setContextResumeData(parsedData)
    setJustParsed(true)
    toast.success("Resume parsed!", {
      description: "Review your details below and click Save when ready.",
    })
    setModalStep("upload")
    setParsedData(null)
    setError(null)
    onClose()
  }
  const sanitizeError = (msg: string): string => {
    const raw = msg.toLowerCase()
    if (
      raw.includes('forbidden') ||
      raw.includes('401') ||
      raw.includes('403') ||
      raw.includes('500') ||
      raw.includes('internal server') ||
      raw.includes('unauthorized') ||
      raw.includes('http ') ||
      raw.includes('network') ||
      raw.includes('failed to fetch')
    ) {
      return 'Something went wrong. Please try again.'
    }
    return msg
  }
  const handleError = (errorMsg: string) => {
    const friendly = sanitizeError(errorMsg)
    setError(friendly)
    toast.error(friendly)
  }
  const isBlocked = modalStep === "parsing"
  const handleClose = () => {
    if (isBlocked) return
    setModalStep("upload")
    setParsedData(null)
    setError(null)
    onClose()
  }
  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent
        showCloseButton={false}
        className="border-border bg-card sm:max-w-lg"
        onPointerDownOutside={(e) => { if (isBlocked) e.preventDefault() }}
        onEscapeKeyDown={(e) => { if (isBlocked) e.preventDefault() }}
      >
        <div className="flex items-center gap-2">
          {["upload", "parsing"].map((step, i) => (
            <div key={step} className="flex items-center gap-2">
              <div
                className={`h-1.5 w-8 rounded-full transition-all duration-500`}
                style={{
                  background: i <= ["upload", "parsing"].indexOf(modalStep)
                    ? "var(--foreground)"
                    : "var(--border)"
                }}
              />
            </div>
          ))}
        </div>
        {modalStep === "upload" && (
          <UploadStep
            onUploadStart={handleUploadStart}
            onSkip={handleClose}
            onError={handleError}
          />
        )}
        {modalStep === "parsing" && (
          <ParsingStep
            onComplete={handleParsingComplete}
            parsedData={parsedData}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
