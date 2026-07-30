"use client"
import { useState } from "react"
import { User, Eye, EyeOff, Trash2, Loader2, Lock, Save } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog"
import { changePassword, deleteAccount, updateAccountInfo } from "@/lib/api"
import type { AuthUser } from "@/lib/auth"

export function AccountTab({
  user,
  onAccountDeleted,
  onAccountUpdated,
}: {
  user?: AuthUser | null
  onAccountDeleted: () => void
  onAccountUpdated?: (updates: { name: string; email: string }) => void
}) {
  const [fullName, setFullName] = useState(user?.name || "")
  const [email, setEmail] = useState(user?.email || "")
  const [savingInfo, setSavingInfo] = useState(false)
  const [currentPw, setCurrentPw] = useState("")
  const [newPw, setNewPw] = useState("")
  const [confirmPw, setConfirmPw] = useState("")
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [changingPw, setChangingPw] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deletePw, setDeletePw] = useState("")
  const [deleting, setDeleting] = useState(false)
  const isGoogle = user?.auth_provider === "google"

  const handleSaveInfo = async () => {
    if (!fullName.trim()) { toast.error("Name cannot be empty."); return }
    setSavingInfo(true)
    try {
      await updateAccountInfo(fullName.trim(), email.trim())
      onAccountUpdated?.({ name: fullName.trim(), email: email.trim() })
      toast.success("Account info saved.")
    } catch (e: any) { toast.error(e?.message || "Failed to save.") }
    finally { setSavingInfo(false) }
  }

  const handleChangePw = async () => {
    if (!currentPw || !newPw) { toast.error("Fill in all password fields."); return }
    if (newPw !== confirmPw) { toast.error("Passwords don't match."); return }
    if (newPw.length < 8) { toast.error("Password must be at least 8 characters."); return }
    setChangingPw(true)
    try {
      await changePassword(currentPw, newPw)
      toast.success("Password changed.")
      setCurrentPw(""); setNewPw(""); setConfirmPw("")
    } catch (e: any) { toast.error(e?.message || "Failed to change password.") }
    finally { setChangingPw(false) }
  }

  const handleDeleteAccount = async () => {
    if (!isGoogle && !deletePw) { toast.error("Enter your password to confirm."); return }
    setDeleting(true)
    try {
      await deleteAccount(isGoogle ? undefined : deletePw)
      toast.success("Account deleted.")
      onAccountDeleted()
    } catch (e: any) { toast.error(e?.message || "Failed to delete account.") }
    finally { setDeleting(false) }
  }

  return (
    <div className="space-y-6">
      
      <div className="dashboard-card">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Account Information</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="account-full-name" className="text-xs text-muted-foreground">Full Name</Label>
            <Input id="account-full-name" value={fullName} onChange={e => setFullName(e.target.value)} className="h-9" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="account-email" className="text-xs text-muted-foreground">Email Address</Label>
            <Input id="account-email" value={email} onChange={e => setEmail(e.target.value)} className="h-9" />
          </div>
        </div>
        <Button className="mt-4 gap-2" onClick={handleSaveInfo} disabled={savingInfo}>
          {savingInfo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Changes
        </Button>
      </div>

      
      {!isGoogle && (
        <div className="dashboard-card">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Change Password</h3>
          <p className="mb-4 text-xs text-muted-foreground">Must be at least 8 characters with uppercase, lowercase, digit, and special character.</p>
          <div className="space-y-3 max-w-md">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="current-password" className="text-xs text-muted-foreground">Current Password</Label>
              <div className="relative">
                <Input id="current-password" type={showCurrent ? "text" : "password"} value={currentPw} onChange={e => setCurrentPw(e.target.value)} className="h-9 pr-9" />
                <button type="button" aria-label={showCurrent ? "Hide current password" : "Show current password"} onClick={() => setShowCurrent(!showCurrent)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showCurrent ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-password" className="text-xs text-muted-foreground">New Password</Label>
              <div className="relative">
                <Input id="new-password" type={showNew ? "text" : "password"} value={newPw} onChange={e => setNewPw(e.target.value)} className="h-9 pr-9" />
                <button type="button" aria-label={showNew ? "Hide new password" : "Show new password"} onClick={() => setShowNew(!showNew)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirm-new-password" className="text-xs text-muted-foreground">Confirm New Password</Label>
              <Input id="confirm-new-password" type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} className="h-9" />
            </div>
            <Button className="gap-2" onClick={handleChangePw} disabled={changingPw}>
              {changingPw ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
              Update Password
            </Button>
          </div>
        </div>
      )}

      
      <div className="dashboard-card ring-1 ring-red-500/20">
        <h3 className="mb-1 text-sm font-semibold text-red-600 dark:text-red-400">Account Management</h3>
        <p className="mb-4 text-xs text-muted-foreground">This action is irreversible. All your data will be permanently deleted.</p>
        <Button variant="outline" className="border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400" onClick={() => setShowDeleteModal(true)}>
          <Trash2 className="mr-2 h-4 w-4" /> Delete Account
        </Button>
      </div>

      <Dialog open={showDeleteModal} onOpenChange={setShowDeleteModal}>
        <DialogContent className="max-w-sm border-border bg-card">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-foreground">Delete your account?</DialogTitle>
            <DialogDescription className="mt-2 text-sm text-muted-foreground">
              This will permanently delete your account, all interviews, scores, and profile data. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {!isGoogle && (
            <div className="mt-3 flex flex-col gap-1.5">
              <Label htmlFor="delete-account-password" className="text-xs text-muted-foreground">Enter your password to confirm</Label>
              <Input id="delete-account-password" type="password" value={deletePw} onChange={e => setDeletePw(e.target.value)} placeholder="Your password" className="h-9" />
            </div>
          )}
          <DialogFooter className="mt-4 flex gap-3">
            <Button variant="outline" className="flex-1" onClick={() => setShowDeleteModal(false)} disabled={deleting}>Cancel</Button>
            <Button variant="destructive" className="flex-1 gap-2" onClick={handleDeleteAccount} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete Forever
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
