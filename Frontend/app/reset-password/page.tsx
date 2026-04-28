"use client"
import { useState, useEffect, Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Loader2, Eye, EyeOff, AlertCircle, CheckCircle2 } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"
import { resetPassword } from "@/lib/auth"
function ResetPasswordForm() {
    const [isLoading, setIsLoading] = useState(false)
    const [password, setPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState(false)
    const searchParams = useSearchParams()
    const router = useRouter()
    const token = searchParams.get("token")
    useEffect(() => {
        if (!token) {
            setError("Invalid or missing reset token. Please request a new password reset link.")
        }
    }, [token])
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!token) return
        if (password !== confirmPassword) {
            setError("Passwords do not match")
            return
        }
        if (password.length < 8) {
            setError("Password must be at least 8 characters long")
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            await resetPassword(token, password)
            setSuccess(true)
            setTimeout(() => {
                router.push("/")
            }, 3000)
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to reset password")
        } finally {
            setIsLoading(false)
        }
    }
    return (
        <div className="w-full max-w-md space-y-8 rounded-2xl border border-border bg-card p-8 shadow-sm">
            <div className="flex flex-col items-center">
                <ThemeLogo size={48} className="mb-6" />
                <h2 className="mt-2 text-center text-2xl font-bold tracking-tight text-foreground">
                    {success ? "Password Reset Complete" : "Set new password"}
                </h2>
                {!success && (
                    <p className="mt-2 text-center text-sm text-muted-foreground">
                        Please enter your new password below.
                    </p>
                )}
            </div>
            {error && (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-600 dark:text-red-400">
                    <AlertCircle className="h-5 w-5 shrink-0" />
                    <p>{error}</p>
                </div>
            )}
            {success ? (
                <div className="flex flex-col items-center justify-center space-y-4 rounded-lg bg-green-50 p-6 text-center dark:bg-green-500/10">
                    <CheckCircle2 className="h-12 w-12 text-green-500" />
                    <p className="text-sm font-medium text-green-800 dark:text-green-300">
                        Your password has been successfully reset!
                    </p>
                    <p className="text-xs text-green-600 dark:text-green-400">
                        Redirecting you to login...
                    </p>
                </div>
            ) : (
                <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
                    <div className="space-y-4">
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="password" className="text-sm font-medium text-muted-foreground">
                                New Password
                            </Label>
                            <div className="relative">
                                <Input
                                    id="password"
                                    type={showPassword ? "text" : "password"}
                                    disabled={!token || isLoading}
                                    required
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="h-11 border-border bg-background pr-10 text-foreground"
                                    placeholder="Enter new password"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                >
                                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                            </div>
                        </div>
                        <div className="flex flex-col gap-2">
                            <Label htmlFor="confirmPassword" className="text-sm font-medium text-muted-foreground">
                                Confirm Password
                            </Label>
                            <Input
                                id="confirmPassword"
                                type={showPassword ? "text" : "password"}
                                disabled={!token || isLoading}
                                required
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                className="h-11 border-border bg-background text-foreground"
                                placeholder="Confirm new password"
                            />
                        </div>
                    </div>
                    <Button
                        type="submit"
                        disabled={!token || isLoading}
                        className="h-11 w-full bg-primary font-semibold text-primary-foreground hover:bg-primary/90"
                    >
                        {isLoading ? (
                            <>
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                Resetting...
                            </>
                        ) : (
                            "Reset Password"
                        )}
                    </Button>
                </form>
            )}
        </div>
    )
}
export default function ResetPasswordPage() {
    return (
        <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8">
            <Suspense fallback={
                <div className="flex items-center justify-center">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                </div>
            }>
                <ResetPasswordForm />
            </Suspense>
        </div>
    )
}
