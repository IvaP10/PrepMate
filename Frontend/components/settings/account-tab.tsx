"use client"
import { useState, useRef } from "react"
import { User, Camera, Eye, EyeOff, Trash2, Loader2, Lock, Save } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog"
import { changePassword, deleteAccount, updateAccountInfo, uploadAvatar } from "@/lib/api"
import type { AuthUser } from "@/lib/auth"

export function AccountTab({ user, onAccountDeleted }: { user?: AuthUser | null; onAccountDeleted: () => void }) {
  const [fullName, setFullName] = useState(user?.name || "")
  const [email, setEmail] = useState(user?.email || "")
  const [savingInfo, setSavingInfo] = useState(false)
  const [currentPw, setCurrentPw] = useState("")
  const [newPw, setNewPw] = useState("")
  const [confirmPw, setConfirmPw] = useState("")
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [changingPw, setChangingPw] = useState(false)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(user?.avatar_url || null)
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deletePw, setDeletePw] = useState("")
  const [deleting, setDeleting] = useState(false)
  const isGoogle = user?.auth_provider === "google"

  const handleSaveInfo = async () => {
    if (!fullName.trim()) { toast.error("Name cannot be empty."); return }
    setSavingInfo(true)
    try {
      await updateAccountInfo(fullName.trim(), email.trim())
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

  const handleAvatarSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 200_000) { toast.error("Image must be under 200 KB."); return }
    const reader = new FileReader()
    reader.onload = async () => {
      const base64 = reader.result as string
      setAvatarPreview(base64)
      setUploadingAvatar(true)
      try {
        await uploadAvatar(base64)
        toast.success("Avatar updated.")
      } catch (e: any) { toast.error(e?.message || "Failed to upload avatar.") }
      finally { setUploadingAvatar(false) }
    }
    reader.readAsDataURL(file)
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
      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Profile Photo</h3>
        <div className="flex items-center gap-5">
          <button type="button" onClick={() => fileRef.current?.click()}
            className="group relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-full border-2 border-dashed border-border bg-secondary/30 transition-colors hover:border-primary/40">
            {avatarPreview ? (
              <img src={avatarPreview} alt="Avatar" className="h-full w-full object-cover" />
            ) : (
              <User className="h-8 w-8 text-muted-foreground" />
            )}
            <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100 rounded-full">
              <Camera className="h-5 w-5 text-white" />
            </div>
          </button>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarSelect} />
          <div>
            <p className="text-sm text-foreground font-medium">Upload a photo</p>
            <p className="text-xs text-muted-foreground mt-1">JPG or PNG, max 200 KB</p>
            {uploadingAvatar && <p className="text-xs text-primary mt-1 flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Uploading...</p>}
          </div>
        </div>
      </div>

      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Account Information</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Full Name</Label>
            <Input value={fullName} onChange={e => setFullName(e.target.value)} className="h-9" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Email Address</Label>
            <Input value={email} onChange={e => setEmail(e.target.value)} className="h-9" />
          </div>
        </div>
        <Button className="mt-4 gap-2" onClick={handleSaveInfo} disabled={savingInfo}>
          {savingInfo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Changes
        </Button>
      </div>

      
      {!isGoogle && (
        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <div className="mb-1 flex items-center gap-2">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold text-foreground">Change Password</h3>
          </div>
          <p className="mb-4 text-xs text-muted-foreground">Must be at least 8 characters with uppercase, lowercase, digit, and special character.</p>
          <div className="space-y-3 max-w-md">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Current Password</Label>
              <div className="relative">
                <Input type={showCurrent ? "text" : "password"} value={currentPw} onChange={e => setCurrentPw(e.target.value)} className="h-9 pr-9" />
                <button type="button" onClick={() => setShowCurrent(!showCurrent)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showCurrent ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">New Password</Label>
              <div className="relative">
                <Input type={showNew ? "text" : "password"} value={newPw} onChange={e => setNewPw(e.target.value)} className="h-9 pr-9" />
                <button type="button" onClick={() => setShowNew(!showNew)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Confirm New Password</Label>
              <Input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} className="h-9" />
            </div>
            <Button className="gap-2" onClick={handleChangePw} disabled={changingPw}>
              {changingPw ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
              Update Password
            </Button>
          </div>
        </div>
      )}

      
      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6">
        <h3 className="mb-1 text-sm font-semibold text-red-400">Danger Zone</h3>
        <p className="mb-4 text-xs text-muted-foreground">This action is irreversible. All your data will be permanently deleted.</p>
        <Button variant="outline" className="border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-400" onClick={() => setShowDeleteModal(true)}>
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
              <Label className="text-xs text-muted-foreground">Enter your password to confirm</Label>
              <Input type="password" value={deletePw} onChange={e => setDeletePw(e.target.value)} placeholder="Your password" className="h-9" />
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
