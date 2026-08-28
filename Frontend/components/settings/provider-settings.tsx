"use client"

import { useEffect, useState } from "react"
import { Check, KeyRound, Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { API_CONFIG } from "@/lib/config"

type ProviderId = "openai" | "anthropic" | "google" | "openai_compatible"

type LocalSettings = {
  provider: ProviderId
  model: string
  endpoint: string
  has_api_key: boolean
  requires_api_key?: boolean
}

const PROVIDERS: { id: ProviderId; label: string; defaultModel: string; placeholder: string }[] = [
  { id: "openai", label: "OpenAI", defaultModel: "gpt-5-mini", placeholder: "gpt-5-mini" },
  { id: "anthropic", label: "Anthropic", defaultModel: "claude-sonnet-5", placeholder: "claude-sonnet-5" },
  { id: "google", label: "Google Gemini", defaultModel: "gemini-3.7-flash", placeholder: "gemini-3.7-flash" },
  { id: "openai_compatible", label: "OpenAI-compatible endpoint", defaultModel: "your-model-name", placeholder: "your-model-name" },
]

type SecureStorageAction = "save" | "test" | "remove"

function endpointRequiresApiKey(endpoint: string): boolean {
  try {
    const hostname = new URL(endpoint).hostname.toLowerCase()
    return !["localhost", "127.0.0.1", "::1"].includes(hostname)
  } catch {
    return true
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_CONFIG.BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || body.message || `Request failed (${response.status})`)
  return body as T
}

export function ProviderSettings() {
  const [settings, setSettings] = useState<LocalSettings>({
    provider: "openai",
    model: "gpt-5-mini",
    endpoint: "",
    has_api_key: false,
  })
  const [apiKey, setApiKey] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [secureStorageAction, setSecureStorageAction] = useState<SecureStorageAction | null>(null)

  useEffect(() => {
    request<LocalSettings>("/local/settings")
      .then(setSettings)
      .catch((error) => toast.error(error instanceof Error ? error.message : "Could not load local settings."))
      .finally(() => setLoading(false))
  }, [])

  const selectedProvider = PROVIDERS.find((provider) => provider.id === settings.provider) || PROVIDERS[0]

  const performSave = async () => {
    if (!settings.model.trim()) {
      toast.error("Enter a model name.")
      return
    }
    if (settings.provider === "openai_compatible" && !settings.endpoint.trim()) {
      toast.error("Enter the base URL for the OpenAI-compatible provider.")
      return
    }
    setSaving(true)
    try {
      const next = await request<LocalSettings>("/local/settings", {
        method: "PUT",
        body: JSON.stringify({
          provider: settings.provider,
          model: settings.model.trim(),
          endpoint: settings.endpoint.trim(),
          api_key: apiKey.trim() || undefined,
        }),
      })
      setSettings(next)
      setApiKey("")
      toast.success("Connection verified. Provider settings saved locally.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save provider settings.")
    } finally {
      setSaving(false)
    }
  }

  const save = () => {
    if (!settings.model.trim()) {
      toast.error("Enter a model name.")
      return
    }
    if (settings.provider === "openai_compatible" && !settings.endpoint.trim()) {
      toast.error("Enter the base URL for the OpenAI-compatible provider.")
      return
    }
    if (settings.requires_api_key !== false && !apiKey.trim() && !settings.has_api_key) {
      toast.error("Enter the selected provider API key.")
      return
    }
    if (apiKey.trim() || settings.has_api_key) {
      setSecureStorageAction("save")
      return
    }
    void performSave()
  }

  const performTest = async () => {
    setTesting(true)
    try {
      await request<{ ok: boolean }>("/local/settings/test", { method: "POST" })
      toast.success("Provider connection is working.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Provider connection failed.")
    } finally {
      setTesting(false)
    }
  }

  const test = () => {
    if (settings.has_api_key) {
      setSecureStorageAction("test")
      return
    }
    void performTest()
  }

  const performRemoveKey = async () => {
    try {
      const next = await request<LocalSettings>("/local/settings/key", { method: "DELETE" })
      setSettings(next)
      toast.success("API key removed from the operating-system keychain.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not remove the API key.")
    }
  }

  const removeKey = () => setSecureStorageAction("remove")

  const approveSecureStorage = () => {
    const action = secureStorageAction
    setSecureStorageAction(null)
    if (action === "save") void performSave()
    if (action === "test") void performTest()
    if (action === "remove") void performRemoveKey()
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="space-y-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Local settings</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">Choose your AI provider</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            PrepMate runs on this laptop. Your API key is stored in the operating-system keychain and is sent only to the provider you choose.
          </p>
          <p className="mt-2 text-xs leading-5 text-amber-700 dark:text-amber-300">
            PrepMate does not charge for use. Your provider may charge for requests and may retain prompts under its own terms; a loopback endpoint keeps requests on this computer unless that server forwards them.
          </p>
        </div>

        <div className="dashboard-card space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="local-provider">Provider</Label>
            <select
              id="local-provider"
              value={settings.provider}
              onChange={(event) => {
                const provider = PROVIDERS.find((item) => item.id === event.target.value) || PROVIDERS[0]
                setApiKey("")
                setSettings((current) => ({
                  ...current,
                  provider: provider.id,
                  model: provider.defaultModel,
                  endpoint: provider.id === "openai_compatible" ? current.endpoint : "",
                  has_api_key: false,
                  requires_api_key: provider.id !== "openai_compatible" || endpointRequiresApiKey(current.endpoint),
                }))
              }}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
            >
              {PROVIDERS.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="local-model">Model name</Label>
            <Input id="local-model" value={settings.model} placeholder={selectedProvider.placeholder} onChange={(event) => setSettings((current) => ({ ...current, model: event.target.value }))} />
            <p className="text-xs text-muted-foreground">Type the exact model name accepted by your provider. The example is only a suggestion and is not an authoritative catalog.</p>
          </div>

          {settings.provider === "openai_compatible" && (
            <div className="space-y-1.5">
              <Label htmlFor="local-endpoint">Base URL</Label>
              <Input id="local-endpoint" value={settings.endpoint} placeholder="http://localhost:11434/v1" onChange={(event) => {
                const endpoint = event.target.value
                setSettings((current) => ({ ...current, endpoint, requires_api_key: endpointRequiresApiKey(endpoint) }))
              }} />
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="local-api-key">API key</Label>
            <Input id="local-api-key" type="password" autoComplete="off" value={apiKey} placeholder={settings.has_api_key ? "Stored securely — enter a new key to replace it" : "Paste your provider API key"} onChange={(event) => setApiKey(event.target.value)} />
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><KeyRound className="h-3.5 w-3.5" />The key never goes into the app database or browser storage.</p>
            {settings.provider !== "openai" && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                Voice transcription currently requires OpenAI. Other providers can power text generation, reports, and coaching.
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={save} disabled={saving}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}Test and save</Button>
            <Button variant="outline" onClick={test} disabled={testing || (!settings.has_api_key && settings.requires_api_key !== false)}>{testing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}Test connection</Button>
            {settings.has_api_key && <Button variant="ghost" className="text-destructive" onClick={removeKey}><Trash2 className="mr-2 h-4 w-4" />Remove key</Button>}
          </div>
        </div>

        <div className="rounded-lg border border-border/60 bg-secondary/20 p-4 text-xs leading-5 text-muted-foreground">
          Resumes, job descriptions, interview history, reports, performance data, saved roles, and preferences remain in this app&apos;s local storage. Provider prompts and voice transcription go directly to the provider you select. Interviewer questions remain readable text in this alpha.
        </div>

        <Dialog open={secureStorageAction !== null} onOpenChange={(open) => { if (!open && !saving && !testing) setSecureStorageAction(null) }}>
          <DialogContent showCloseButton={!saving && !testing}>
            <DialogHeader>
              <DialogTitle>Allow secure storage access?</DialogTitle>
              <DialogDescription className="leading-6">
                PrepMate will {secureStorageAction === "remove" ? "remove the saved API key from" : secureStorageAction === "test" ? "read the saved API key from" : "save or read the API key in"} your operating-system Keychain. After you choose Yes, macOS may ask for your login password. PrepMate never sees or stores that password, and it will not request Keychain access merely because the app opened.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setSecureStorageAction(null)}>Cancel</Button>
              <Button onClick={approveSecureStorage}>Yes, continue</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
    </div>
  )
}
