"use client"
import { useState, useEffect } from "react"
import { Bell, Calendar, Flame, Mail, Loader2, Save } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { getNotificationPrefs, updateNotificationPrefs } from "@/lib/api"
import type { NotificationPrefs } from "@/lib/api"

function Toggle({ checked, onChange, label, description, icon: Icon }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; description: string; icon: any
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-secondary/20 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-card ring-1 ring-border/50">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="mt-0.5 text-xs text-muted-foreground leading-5">{description}</p>
        </div>
      </div>
      <button type="button" onClick={() => onChange(!checked)} aria-label={`Toggle ${label}`}
        className={`relative mt-1 h-6 w-11 shrink-0 rounded-full border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${checked ? "bg-primary border-primary/60" : "bg-secondary border-border"}`}>
        <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-md transition-transform duration-200 ${checked ? "translate-x-5" : "translate-x-0"}`} />
      </button>
    </div>
  )
}

export function NotificationsTab() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [inactiveEnabled, setInactiveEnabled] = useState(false)
  const [inactiveDays, setInactiveDays] = useState("7")
  const [targetDate, setTargetDate] = useState("")
  const [weeklySummary, setWeeklySummary] = useState(false)
  const [streakReminder, setStreakReminder] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const prefs = await getNotificationPrefs()
        setInactiveEnabled(prefs.inactive_reminder_days !== null)
        setInactiveDays(prefs.inactive_reminder_days?.toString() || "7")
        setTargetDate(prefs.target_date || "")
        setWeeklySummary(prefs.weekly_summary)
        setStreakReminder(prefs.streak_reminder)
      } catch { }
      finally { setLoading(false) }
    }
    load()
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateNotificationPrefs({
        inactive_reminder_days: inactiveEnabled ? parseInt(inactiveDays) : null,
        target_date: targetDate || null,
        weekly_summary: weeklySummary,
        streak_reminder: streakReminder,
      })
      toast.success("Notification preferences saved.")
    } catch (e: any) { toast.error(e?.message || "Failed to save preferences.") }
    finally { setSaving(false) }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">Loading preferences...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Email Notifications</h3>
        <p className="mb-5 text-xs text-muted-foreground">Choose what emails you receive from InterAI.</p>
        <div className="space-y-3">
          <div className="space-y-3">
            <Toggle checked={inactiveEnabled} onChange={setInactiveEnabled} icon={Mail}
              label="Inactivity reminder" description="Get an email if you haven't practiced in a while." />
            {inactiveEnabled && (
              <div className="ml-11 flex items-center gap-2">
                <Label className="text-xs text-muted-foreground whitespace-nowrap">Remind after</Label>
                <Select value={inactiveDays} onValueChange={setInactiveDays}>
                  <SelectTrigger className="h-8 w-24"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="3">3 days</SelectItem>
                    <SelectItem value="5">5 days</SelectItem>
                    <SelectItem value="7">7 days</SelectItem>
                    <SelectItem value="14">14 days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <div className="space-y-3">
            <div className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-secondary/20 p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-card ring-1 ring-border/50">
                  <Calendar className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">Interview target date</p>
                  <p className="mt-0.5 text-xs text-muted-foreground leading-5">Set a date and get daily reminders as it approaches.</p>
                </div>
              </div>
              <Input type="date" value={targetDate} onChange={e => setTargetDate(e.target.value)}
                className="h-8 w-40 shrink-0 text-xs" />
            </div>
          </div>

          <Toggle checked={weeklySummary} onChange={setWeeklySummary} icon={Bell}
            label="Weekly performance summary" description="Receive a weekly email summarising your scores and progress." />

          <Toggle checked={streakReminder} onChange={setStreakReminder} icon={Flame}
            label="Streak reminder" description="Get a nudge if you're about to break your practice streak." />
        </div>
        <Button className="mt-5 gap-2" onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Preferences
        </Button>
      </div>
    </div>
  )
}
