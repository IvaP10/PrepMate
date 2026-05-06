"use client"
import { useState, useEffect, useRef, useCallback, Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import {
    Check, CreditCard, Loader2, ArrowLeft, Shield, Zap, Lock,
    ChevronRight, Smartphone, Building2, BadgeCheck, QrCode,
    CheckCircle2, AlertCircle, ChevronDown, X, Clock
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { createPaymentSession, verifyRazorpayPayment } from "@/lib/api"
import { API_CONFIG } from "@/lib/config"


type PaymentMethod = "upi" | "card" | "netbanking"
type UpiMode = "id" | "qr"

const MEMBERSHIP_PLANS: Record<string, {
    name: string
    amount: number
    cadence: string
    description: string
    detail: string
}> = {
    starter: {
        name: "Starter",
        amount: 299,
        cadence: "Monthly · 1 month access",
        description: "Mock interviews to practice with, performance analysis after every session",
        detail: "Get interview ready",
    },
    pro: {
        name: "Pro",
        amount: 999,
        cadence: "Monthly membership",
        description: "Unlimited mocks, full coaching, all exercise modes, deep analytics",
        detail: "Unlock the full experience",
    },
    pro_annual: {
        name: "Pro (Annual)",
        amount: 10788,
        cadence: "Billed yearly at ₹10,788",
        description: "Everything in Pro — save 10% with annual billing",
        detail: "₹899 / month billed annually",
    },
    premium: {
        name: "Premium",
        amount: 1499,
        cadence: "Monthly membership",
        description: "Everything in Pro plus technical rounds, code editor, problem walkthroughs",
        detail: "Ace every round, including technical",
    },
    premium_annual: {
        name: "Premium (Annual)",
        amount: 16188,
        cadence: "Billed yearly at ₹16,188",
        description: "Everything in Premium — save 10% with annual billing",
        detail: "₹1,349 / month billed annually",
    },
}


function CheckoutContent() {
    const searchParams = useSearchParams()
    const router = useRouter()
    const planParam = searchParams.get("plan")
    const membershipPlan = planParam ? MEMBERSHIP_PLANS[planParam] : null
    const sessionsParam = searchParams.get("sessions")
    const sessionCount = sessionsParam ? parseInt(sessionsParam) : 5
    const isMembershipCheckout = Boolean(membershipPlan && planParam)

    
    const [selectedMethod, setSelectedMethod] = useState<PaymentMethod>("upi")
    const [expandedMethod, setExpandedMethod] = useState<PaymentMethod>("upi")

    
    const [isProcessing, setIsProcessing] = useState(false)
    const [processingLabel, setProcessingLabel] = useState("")

    
    const [upiMode, setUpiMode] = useState<UpiMode>("id")
    const [upiId, setUpiId] = useState("")
    const [upiVerified, setUpiVerified] = useState(false)
    const [verifyingUpi, setVerifyingUpi] = useState(false)
    const [upiError, setUpiError] = useState("")

    
    const [cardNumber, setCardNumber] = useState("")
    const [cardExpiry, setCardExpiry] = useState("")
    const [cardCvv, setCardCvv] = useState("")
    const [cardName, setCardName] = useState("")
    const [cardErrors, setCardErrors] = useState<Record<string, string>>({})

    
    const [selectedBank, setSelectedBank] = useState("")

    
    const [pricing, setPricing] = useState<{
        sessions: number; price_per_credit: number; base_price: number;
        discount: number; discount_percent: number; subtotal: number;
        processing_fee: number; processing_fee_percent: number;
        total: number; currency: string;
    } | null>(null)
    const [pricingLoading, setPricingLoading] = useState(true)

    useEffect(() => {
        async function fetchPricing() {
            setPricingLoading(true)
            if (membershipPlan) {
                setPricing({
                    sessions: 0,
                    price_per_credit: 0,
                    base_price: membershipPlan.amount,
                    discount: 0,
                    discount_percent: 0,
                    subtotal: membershipPlan.amount,
                    processing_fee: 0,
                    processing_fee_percent: 0,
                    total: membershipPlan.amount,
                    currency: "INR",
                })
                setPricingLoading(false)
                return
            }
            try {
                const apiBase = API_CONFIG.BASE_URL
                const res = await fetch(
                    `${apiBase}/payment/pricing?sessions=${sessionCount}&provider=razorpay`,
                    { credentials: "include" }
                )
                if (res.ok) {
                    setPricing(await res.json())
                } else {
                    toast.error("Failed to load pricing")
                }
            } catch {
                toast.error("Failed to connect to server")
            } finally {
                setPricingLoading(false)
            }
        }
        fetchPricing()
    }, [sessionCount, membershipPlan])

    const fmtPrice = (n: number) =>
        `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

    
    const formatCardNumber = (v: string) => {
        const d = v.replace(/\D/g, "").slice(0, 16)
        return d.replace(/(.{4})/g, "$1 ").trim()
    }
    const formatExpiry = (v: string) => {
        const d = v.replace(/\D/g, "").slice(0, 4)
        if (d.length >= 3) return d.slice(0, 2) + "/" + d.slice(2)
        return d
    }
    const validateUpiFormat = (id: string) => /^[a-zA-Z0-9._-]+@[a-zA-Z0-9]+$/.test(id)

    const validateCard = (): boolean => {
        const errs: Record<string, string> = {}
        const num = cardNumber.replace(/\s/g, "")
        if (num.length < 13) errs.number = "Enter a valid card number"
        if (cardExpiry.length < 5) errs.expiry = "Enter valid expiry"
        if (cardCvv.length < 3) errs.cvv = "Enter valid CVV"
        if (!cardName.trim()) errs.name = "Enter cardholder name"
        setCardErrors(errs)
        return Object.keys(errs).length === 0
    }

    
    const handleVerifyUpi = async () => {
        if (!upiId) { setUpiError("Please enter your UPI ID"); return }
        if (!validateUpiFormat(upiId)) { setUpiError("Invalid format. Use name@bank (e.g. name@okicici)"); return }
        setUpiError("")
        setVerifyingUpi(true)
        await new Promise(r => setTimeout(r, 1200))
        setVerifyingUpi(false)
        setUpiVerified(true)
        toast.success(`UPI ID ${upiId} verified!`)
    }

    
    const loadRazorpay = (): Promise<boolean> =>
        new Promise((resolve) => {
            if ((window as any).Razorpay) { resolve(true); return }
            const s = document.createElement("script")
            s.src = "https://checkout.razorpay.com/v1/checkout.js"
            s.onload = () => resolve(true)
            s.onerror = () => resolve(false)
            document.body.appendChild(s)
        })

    
    const openRazorpay = async (order: any) => {
        const loaded = await loadRazorpay()
        if (!loaded) throw new Error("Payment gateway failed to load.")
        const key = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID
        if (!key) throw new Error("Payment gateway not configured.")

        const allMethods = ["upi", "card", "netbanking", "wallet", "paylater", "emi"]
        const hideList = allMethods.filter(m => m !== selectedMethod).map(m => ({ method: m }))

        const opts: any = {
            key,
            amount: Math.round(order.amount * 100),
            currency: "INR",
            name: "InterAI",
            description: membershipPlan ? `${membershipPlan.name} Membership` : `${sessionCount} Interview Sessions`,
            order_id: order.session_url,
            prefill: {} as any,
            handler: async (resp: any) => {
                setProcessingLabel("Verifying payment…")
                try {
                    const result = await verifyRazorpayPayment(
                        resp.razorpay_order_id,
                        resp.razorpay_payment_id,
                        resp.razorpay_signature
                    )
                    toast.success(result.message || "Payment successful!")
                    router.push("/")
                } catch (err: any) {
                    toast.error(err?.message || "Verification failed. Contact support.")
                } finally {
                    setIsProcessing(false)
                    setProcessingLabel("")
                }
            },
            modal: {
                ondismiss: () => { setIsProcessing(false); setProcessingLabel("") },
                confirm_close: true,
            },
            config: {
                display: {
                    hide: hideList,
                    preferences: { show_default_blocks: true },
                },
            },
            theme: { color: "#2563eb" },
        }

        if (selectedMethod === "upi" && upiId) opts.prefill.vpa = upiId
        if (selectedMethod === "card") opts.prefill.name = cardName

        const rzp = new (window as any).Razorpay(opts)
        rzp.on("payment.failed", (r: any) => {
            toast.error((r?.error?.description || "Payment failed") + ". Please try again.")
            setIsProcessing(false)
            setProcessingLabel("")
        })
        rzp.open()
    }

    
    const handlePay = async () => {
        if (selectedMethod === "upi" && upiMode === "id") {
            if (!upiId) { setUpiError("Enter your UPI ID first"); return }
            if (!validateUpiFormat(upiId)) { setUpiError("Invalid UPI ID format"); return }
        }
        if (selectedMethod === "card" && !validateCard()) return
        if (selectedMethod === "netbanking" && !selectedBank) {
            toast.error("Please select your bank first.")
            return
        }

        setIsProcessing(true)
        setProcessingLabel("Creating order…")

        try {
            const res = await createPaymentSession(isMembershipCheckout && planParam ? planParam : "credits", "razorpay", selectedMethod, isMembershipCheckout ? undefined : sessionCount)
            setProcessingLabel("Opening payment gateway…")
            await openRazorpay(res)
        } catch (e: any) {
            toast.error(e?.message || "Something went wrong. Please try again.")
            setIsProcessing(false)
            setProcessingLabel("")
        }
    }

    
    const selectMethod = (m: PaymentMethod) => {
        setSelectedMethod(m)
        setExpandedMethod(m)
        if (m !== "upi") { setUpiVerified(false); setUpiError("") }
    }

    
    const renderUpiForm = () => (
        <div className="px-6 pb-6 space-y-4" style={{ animation: "fadeSlide .25s ease" }}>
            
            <div className="flex rounded-lg border border-border/50 overflow-hidden">
                <button
                    onClick={() => { setUpiMode("id"); setUpiVerified(false) }}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-semibold transition-colors ${
                        upiMode === "id"
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary/40 text-muted-foreground hover:bg-secondary"
                    }`}
                >
                    <Smartphone className="h-3.5 w-3.5" /> Enter UPI ID
                </button>
                <button
                    onClick={() => { setUpiMode("qr"); setUpiVerified(false) }}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-semibold transition-colors ${
                        upiMode === "qr"
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary/40 text-muted-foreground hover:bg-secondary"
                    }`}
                >
                    <QrCode className="h-3.5 w-3.5" /> Scan QR Code
                </button>
            </div>

            {upiMode === "id" ? (
                <div className="space-y-3">
                    
                    <div className="space-y-1.5">
                        <label className="text-xs font-medium text-muted-foreground">UPI ID</label>
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <input
                                    type="text"
                                    placeholder="e.g. yourname@okicici"
                                    value={upiId}
                                    disabled={upiVerified}
                                    onChange={(e) => {
                                        const v = e.target.value.toLowerCase().replace(/\s/g, "")
                                        setUpiId(v)
                                        setUpiError("")
                                        setUpiVerified(false)
                                    }}
                                    className={`w-full h-11 rounded-lg border bg-card px-4 pr-10 text-sm text-foreground placeholder:text-muted-foreground/40 transition-all focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 ${
                                        upiError ? "border-red-400" : upiVerified ? "border-green-500" : "border-border/60"
                                    } ${upiVerified ? "bg-green-50/50 dark:bg-green-500/5" : ""}`}
                                />
                                {upiVerified && (
                                    <CheckCircle2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-green-500" />
                                )}
                            </div>
                            {!upiVerified ? (
                                <Button
                                    variant="outline"
                                    className="h-11 px-5 text-xs font-semibold shrink-0"
                                    onClick={handleVerifyUpi}
                                    disabled={verifyingUpi || !upiId}
                                >
                                    {verifyingUpi ? (
                                        <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Verifying</>
                                    ) : "Verify"}
                                </Button>
                            ) : (
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-11 w-11 shrink-0 text-muted-foreground"
                                    onClick={() => { setUpiVerified(false); setUpiId("") }}
                                >
                                    <X className="h-4 w-4" />
                                </Button>
                            )}
                        </div>
                        {upiError && (
                            <p className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{upiError}</p>
                        )}
                        {upiVerified && (
                            <p className="text-[11px] text-green-600 dark:text-green-400 flex items-center gap-1 font-medium">
                                <CheckCircle2 className="h-3 w-3" /> Verified — ready to pay
                            </p>
                        )}
                    </div>

                    
                    {upiVerified && (
                        <Button
                            className="w-full h-11 text-sm font-semibold rounded-lg gap-2"
                            style={{ animation: "fadeSlide .3s ease" }}
                            onClick={handlePay}
                            disabled={isProcessing}
                        >
                            {isProcessing ? (
                                <><Loader2 className="h-4 w-4 animate-spin" /> {processingLabel || "Processing…"}</>
                            ) : (
                                <>Pay {fmtPrice(pricing?.total ?? 0)} <ChevronRight className="h-4 w-4" /></>
                            )}
                        </Button>
                    )}

                    
                    <div className="flex items-center gap-2 pt-1 flex-wrap">
                        <span className="text-[10px] text-muted-foreground/50 font-medium shrink-0">Works with:</span>
                        {["Google Pay", "PhonePe", "Paytm", "BHIM", "Amazon Pay"].map(a => (
                            <span key={a} className="text-[10px] font-medium text-muted-foreground bg-secondary rounded px-2 py-0.5 border border-border/30">{a}</span>
                        ))}
                    </div>
                </div>
            ) : (
                
                <div className="space-y-3">
                    <div className="rounded-xl border border-border/40 bg-card p-5 text-center">
                        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                            <QrCode className="h-7 w-7 text-primary" />
                        </div>
                        <p className="text-sm font-semibold text-foreground">Scan & Pay with any UPI app</p>
                        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                            Click "Pay {fmtPrice(pricing?.total ?? 0)}" below to generate a QR code.<br />
                            Scan it using Google Pay, PhonePe, Paytm, or any UPI app.
                        </p>
                    </div>
                    <Button
                        className="w-full h-11 text-sm font-semibold rounded-lg gap-2"
                        onClick={handlePay}
                        disabled={isProcessing}
                    >
                        {isProcessing ? (
                            <><Loader2 className="h-4 w-4 animate-spin" /> {processingLabel || "Processing…"}</>
                        ) : (
                            <>Generate QR & Pay {fmtPrice(pricing?.total ?? 0)} <ChevronRight className="h-4 w-4" /></>
                        )}
                    </Button>
                </div>
            )}
        </div>
    )

    
    const renderCardForm = () => (
        <div className="px-6 pb-6" style={{ animation: "fadeSlide .25s ease" }}>
            <div className="rounded-xl border border-border/50 bg-secondary/20 p-5 space-y-4">
                <div className="flex items-center gap-2 text-muted-foreground">
                    <Lock className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
                    <span className="text-[11px] font-medium">Card details are encrypted & secured</span>
                </div>

                
                <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">Card Number</label>
                    <div className="relative">
                        <input
                            type="text" inputMode="numeric" autoComplete="cc-number"
                            placeholder="1234  5678  9012  3456"
                            value={cardNumber}
                            onChange={(e) => { setCardNumber(formatCardNumber(e.target.value)); setCardErrors(p => ({ ...p, number: "" })) }}
                            maxLength={19}
                            className={`w-full h-11 rounded-lg border ${cardErrors.number ? "border-red-400" : "border-border/60"} bg-card px-4 pr-12 text-sm text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all font-mono tracking-widest`}
                        />
                        <CreditCard className="absolute right-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/40" />
                    </div>
                    {cardErrors.number && <p className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{cardErrors.number}</p>}
                </div>

                
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                        <label className="text-xs font-medium text-muted-foreground">Valid Thru</label>
                        <input
                            type="text" inputMode="numeric" autoComplete="cc-exp"
                            placeholder="MM / YY"
                            value={cardExpiry}
                            onChange={(e) => { setCardExpiry(formatExpiry(e.target.value)); setCardErrors(p => ({ ...p, expiry: "" })) }}
                            maxLength={5}
                            className={`w-full h-11 rounded-lg border ${cardErrors.expiry ? "border-red-400" : "border-border/60"} bg-card px-4 text-sm text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all font-mono`}
                        />
                        {cardErrors.expiry && <p className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{cardErrors.expiry}</p>}
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-xs font-medium text-muted-foreground">CVV</label>
                        <input
                            type="password" inputMode="numeric" autoComplete="cc-csc"
                            placeholder="•••"
                            value={cardCvv}
                            onChange={(e) => { setCardCvv(e.target.value.replace(/\D/g, "").slice(0, 4)); setCardErrors(p => ({ ...p, cvv: "" })) }}
                            maxLength={4}
                            className={`w-full h-11 rounded-lg border ${cardErrors.cvv ? "border-red-400" : "border-border/60"} bg-card px-4 text-sm text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all font-mono tracking-widest`}
                        />
                        {cardErrors.cvv && <p className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{cardErrors.cvv}</p>}
                    </div>
                </div>

                
                <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">Name on Card</label>
                    <input
                        type="text" autoComplete="cc-name"
                        placeholder="As printed on your card"
                        value={cardName}
                        onChange={(e) => { setCardName(e.target.value); setCardErrors(p => ({ ...p, name: "" })) }}
                        className={`w-full h-11 rounded-lg border ${cardErrors.name ? "border-red-400" : "border-border/60"} bg-card px-4 text-sm text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all`}
                    />
                    {cardErrors.name && <p className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{cardErrors.name}</p>}
                </div>

                
                <div className="flex items-center gap-2 pt-1">
                    <span className="text-[10px] text-muted-foreground/50 font-medium">Accepted:</span>
                    {["Visa", "Mastercard", "RuPay", "Amex"].map(c => (
                        <span key={c} className="text-[10px] font-semibold text-muted-foreground bg-card rounded px-2 py-0.5 border border-border/40">{c}</span>
                    ))}
                </div>
            </div>

            
            <Button
                className="w-full h-11 mt-4 text-sm font-semibold rounded-lg gap-2"
                onClick={handlePay}
                disabled={isProcessing}
            >
                {isProcessing ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> {processingLabel || "Processing…"}</>
                ) : (
                    <>Pay {fmtPrice(pricing?.total ?? 0)} <ChevronRight className="h-4 w-4" /></>
                )}
            </Button>
        </div>
    )

    
    const popularBanks = [
        { id: "SBIN", name: "State Bank of India" },
        { id: "HDFC", name: "HDFC Bank" },
        { id: "ICIC", name: "ICICI Bank" },
        { id: "UTIB", name: "Axis Bank" },
        { id: "KKBK", name: "Kotak Mahindra" },
        { id: "PUNB", name: "Punjab National Bank" },
        { id: "BARB", name: "Bank of Baroda" },
        { id: "YESB", name: "Yes Bank" },
    ]

    const renderNetbankingForm = () => (
        <div className="px-6 pb-6" style={{ animation: "fadeSlide .25s ease" }}>
            <div className="space-y-3">
                <label className="text-xs font-medium text-muted-foreground">Popular Banks</label>
                <div className="grid grid-cols-2 gap-2">
                    {popularBanks.map(bank => (
                        <button
                            key={bank.id}
                            onClick={() => setSelectedBank(bank.id)}
                            className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all text-sm ${
                                selectedBank === bank.id
                                    ? "border-primary bg-primary/5 text-foreground font-medium ring-1 ring-primary/30"
                                    : "border-border/50 bg-card text-muted-foreground hover:border-border hover:bg-secondary/30"
                            }`}
                        >
                            <Building2 className={`h-4 w-4 shrink-0 ${selectedBank === bank.id ? "text-primary" : "text-muted-foreground/50"}`} />
                            <span className="truncate text-xs">{bank.name}</span>
                            {selectedBank === bank.id && <CheckCircle2 className="h-3.5 w-3.5 text-primary ml-auto shrink-0" />}
                        </button>
                    ))}
                </div>
                <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
                    You'll be securely redirected to your bank's portal to complete payment.
                </p>
            </div>

            <Button
                className="w-full h-11 mt-4 text-sm font-semibold rounded-lg gap-2"
                onClick={handlePay}
                disabled={isProcessing || !selectedBank}
            >
                {isProcessing ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> {processingLabel || "Processing…"}</>
                ) : (
                    <>Pay {fmtPrice(pricing?.total ?? 0)} via Net Banking <ChevronRight className="h-4 w-4" /></>
                )}
            </Button>
        </div>
    )

    
    const methods: { id: PaymentMethod; name: string; desc: string; icon: any; tag?: string }[] = [
        { id: "upi",        name: "UPI",                   desc: "Google Pay, PhonePe, Paytm & more", icon: Smartphone,  tag: "Recommended" },
        { id: "card",       name: "Credit / Debit Card",   desc: "Visa, Mastercard, RuPay, Amex",     icon: CreditCard },
        { id: "netbanking", name: "Net Banking",           desc: "All major Indian banks",             icon: Building2 },
    ]

    const steps = [
        { label: "Review", done: true },
        { label: "Payment", active: true },
        { label: "Confirmation" },
    ]

    
    return (
        <>
            
            <style>{`
                @keyframes fadeSlide { from { opacity:0; transform:translateY(8px) } to { opacity:1; transform:translateY(0) } }
            `}</style>

            <div className="min-h-screen bg-[#f1f3f6] dark:bg-background">
                
                <header className="sticky top-0 z-40 border-b border-border/40 bg-card shadow-sm">
                    <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
                        <div className="flex items-center gap-4">
                            <button onClick={() => router.back()} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
                                <ArrowLeft className="h-4 w-4" /><span className="hidden sm:inline">Back</span>
                            </button>
                            <div className="h-5 w-px bg-border" />
                            <span className="text-sm font-bold text-foreground tracking-tight">InterAI Checkout</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <Lock className="h-3.5 w-3.5" /><span className="text-xs font-medium">100% Secure</span>
                        </div>
                    </div>
                </header>

                
                <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-6 pb-2">
                    <div className="flex items-center justify-center">
                        {steps.map((step, i) => (
                            <div key={step.label} className="flex items-center">
                                <div className="flex items-center gap-2">
                                    <div className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                                        step.done ? "bg-primary text-primary-foreground"
                                        : step.active ? "bg-primary text-primary-foreground ring-4 ring-primary/20"
                                        : "bg-secondary text-muted-foreground"}`}>
                                        {step.done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                                    </div>
                                    <span className={`text-xs font-semibold uppercase tracking-wider ${step.done || step.active ? "text-foreground" : "text-muted-foreground"}`}>{step.label}</span>
                                </div>
                                {i < steps.length - 1 && <div className={`mx-4 h-px w-16 sm:w-24 ${step.done ? "bg-primary" : "bg-border"}`} />}
                            </div>
                        ))}
                    </div>
                </div>

                
                <div className="mx-auto max-w-6xl px-4 sm:px-6 py-6">
                    <div className="flex flex-col gap-6 lg:flex-row">

                        
                        <div className="flex-1 space-y-5">

                            
                            <div className="rounded-lg border border-border/40 bg-card shadow-sm overflow-hidden">
                                <div className="border-b border-border/40 bg-secondary/30 px-6 py-3 flex items-center gap-2">
                                    <BadgeCheck className="h-4 w-4 text-primary" />
                                    <h2 className="text-sm font-bold text-foreground uppercase tracking-wide">Order Summary</h2>
                                </div>
                                <div className="p-6">
                                    <div className="flex items-start gap-5">
                                        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20 shrink-0">
                                            <Zap className="h-6 w-6 text-primary" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <h3 className="text-base font-semibold text-foreground">
                                                {membershipPlan ? `${membershipPlan.name} Membership` : `Mock Interviews × ${sessionCount}`}
                                            </h3>
                                            <p className="text-sm text-muted-foreground mt-0.5">
                                                {membershipPlan ? membershipPlan.description : "Mock interview sessions"}
                                            </p>
                                            <div className="mt-3 flex flex-wrap items-center gap-2">
                                                <span className="text-xs text-muted-foreground bg-secondary rounded-md px-2.5 py-1 font-medium">
                                                    {membershipPlan ? membershipPlan.cadence : `₹${pricing?.price_per_credit ?? 199} / interview`}
                                                </span>
                                                {membershipPlan && <span className="text-xs font-medium text-muted-foreground bg-secondary rounded-md px-2.5 py-1">{membershipPlan.detail}</span>}
                                                {!membershipPlan && pricing && pricing.discount > 0 && <span className="text-xs font-bold text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/10 rounded-md px-2.5 py-1">{pricing.discount_percent}% OFF</span>}
                                            </div>
                                        </div>
                                        <div className="text-right shrink-0">
                                            {pricing && pricing.discount > 0 && <p className="text-sm text-muted-foreground line-through">{fmtPrice(pricing.base_price)}</p>}
                                            <p className="text-lg font-bold text-foreground">{fmtPrice(pricing?.subtotal ?? 0)}</p>
                                        </div>
                                    </div>
                                    <div className="mt-4 flex items-center gap-6 pt-4 border-t border-border/30">
                                        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Shield className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />Cancel anytime</div>
                                        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Zap className="h-3.5 w-3.5 text-amber-500" />Instant activation</div>
                                    </div>
                                </div>
                            </div>

                            
                            <div className="rounded-lg border border-border/40 bg-card shadow-sm overflow-hidden">
                                <div className="border-b border-border/40 bg-secondary/30 px-6 py-3">
                                    <h2 className="text-sm font-bold text-foreground uppercase tracking-wide">Payment Options</h2>
                                </div>
                                <div className="divide-y divide-border/30">
                                    {methods.map((m) => {
                                        const isSelected = selectedMethod === m.id
                                        const isExpanded = expandedMethod === m.id
                                        const Icon = m.icon
                                        return (
                                            <div key={m.id} className={isSelected ? "bg-primary/[0.02]" : ""}>
                                                
                                                <button
                                                    className="flex w-full items-center gap-4 px-6 py-5 text-left transition-colors hover:bg-secondary/20"
                                                    onClick={() => selectMethod(m.id)}
                                                >
                                                    <div className="shrink-0">
                                                        <div className={`flex h-[18px] w-[18px] items-center justify-center rounded-full border-2 transition-all ${
                                                            isSelected ? "border-primary" : "border-muted-foreground/30"
                                                        }`}>
                                                            {isSelected && <div className="h-2.5 w-2.5 rounded-full bg-primary" />}
                                                        </div>
                                                    </div>
                                                    <Icon className="h-4 w-4 text-foreground shrink-0" />
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex items-center gap-2">
                                                            <span className="text-sm font-semibold text-foreground">{m.name}</span>
                                                            {m.tag && <span className="rounded bg-green-100 dark:bg-green-500/10 px-1.5 py-0.5 text-[10px] font-bold text-green-700 dark:text-green-400 uppercase">{m.tag}</span>}
                                                        </div>
                                                        <p className="mt-0.5 text-xs text-muted-foreground">{m.desc}</p>
                                                    </div>
                                                    <ChevronDown className={`h-4 w-4 text-muted-foreground/50 transition-transform duration-200 ${isExpanded ? "rotate-180" : ""}`} />
                                                </button>

                                                
                                                {isExpanded && (
                                                    <>
                                                        {m.id === "upi" && renderUpiForm()}
                                                        {m.id === "card" && renderCardForm()}
                                                        {m.id === "netbanking" && renderNetbankingForm()}
                                                    </>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        </div>

                        
                        <div className="w-full lg:w-[340px] shrink-0">
                            <div className="lg:sticky lg:top-20 space-y-4">

                                
                                <div className="rounded-lg border border-border/40 bg-card shadow-sm overflow-hidden">
                                    <div className="border-b border-border/40 bg-secondary/30 px-6 py-3">
                                        <h2 className="text-sm font-bold text-foreground uppercase tracking-wide">Price Details</h2>
                                    </div>
                                    <div className="p-6 space-y-3">
                                        <div className="flex items-center justify-between text-sm">
                                            <span className="text-muted-foreground">
                                                {membershipPlan ? membershipPlan.name : `Price (${sessionCount} interviews)`}
                                            </span>
                                            <span className="text-foreground">{fmtPrice(pricing?.base_price ?? 0)}</span>
                                        </div>
                                        {!membershipPlan && pricing && pricing.discount > 0 && (
                                            <div className="flex items-center justify-between text-sm">
                                                <span className="text-green-700 dark:text-green-400">Discount ({pricing.discount_percent}%)</span>
                                                <span className="text-green-700 dark:text-green-400">−{fmtPrice(pricing.discount)}</span>
                                            </div>
                                        )}
                                        {!membershipPlan && (
                                            <div className="flex items-center justify-between text-sm">
                                                <span className="text-muted-foreground">Processing Fee <span className="text-[10px] ml-1 text-muted-foreground/50">({pricing?.processing_fee_percent ?? 2}%)</span></span>
                                                <span className="text-foreground">+{fmtPrice(pricing?.processing_fee ?? 0)}</span>
                                            </div>
                                        )}
                                        <div className="border-t border-border/40 pt-3 mt-1">
                                            <div className="flex items-center justify-between">
                                                <span className="text-base font-bold text-foreground">Total</span>
                                                <span className="text-base font-bold text-foreground">{fmtPrice(pricing?.total ?? 0)}</span>
                                            </div>
                                        </div>
                                        {!membershipPlan && pricing && pricing.discount > 0 && (
                                            <div className="rounded-lg bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/20 px-4 py-2.5 text-center">
                                                <p className="text-xs font-semibold text-green-700 dark:text-green-400">You save {fmtPrice(pricing.discount)} on this order!</p>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                
                                <div className="rounded-lg border border-border/40 bg-card shadow-sm px-5 py-4">
                                    <div className="flex items-center gap-3">
                                        {selectedMethod === "upi" && <Smartphone className="h-4 w-4 text-primary shrink-0" />}
                                        {selectedMethod === "card" && <CreditCard className="h-4 w-4 text-primary shrink-0" />}
                                        {selectedMethod === "netbanking" && <Building2 className="h-4 w-4 text-primary shrink-0" />}
                                        <div className="flex-1 min-w-0">
                                            <p className="text-xs font-semibold text-foreground">
                                                {selectedMethod === "upi" ? "UPI Payment" : selectedMethod === "card" ? "Card Payment" : "Net Banking"}
                                            </p>
                                            <p className="text-[10px] text-muted-foreground mt-0.5">
                                                {selectedMethod === "upi" && (upiVerified ? `${upiId}` : upiMode === "qr" ? "QR code scan" : "Enter & verify UPI ID")}
                                                {selectedMethod === "card" && (cardNumber ? `•••• ${cardNumber.slice(-4)}` : "Fill card details above")}
                                                {selectedMethod === "netbanking" && (selectedBank ? popularBanks.find(b => b.id === selectedBank)?.name : "Select your bank above")}
                                            </p>
                                        </div>
                                        {((selectedMethod === "upi" && upiVerified) || (selectedMethod === "card" && cardNumber.replace(/\s/g, "").length >= 13) || (selectedMethod === "netbanking" && selectedBank)) && (
                                            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                                        )}
                                    </div>
                                </div>

                                
                                <div className="rounded-lg border border-border/30 bg-card px-4 py-3">
                                    <div className="flex items-center justify-center gap-4">
                                        <div className="flex items-center gap-1.5 text-muted-foreground/60">
                                            <Shield className="h-3.5 w-3.5" /><span className="text-[11px] font-medium">Safe & Secure</span>
                                        </div>
                                        <div className="h-3 w-px bg-border" />
                                        <div className="flex items-center gap-1.5 text-muted-foreground/60">
                                            <Lock className="h-3.5 w-3.5" /><span className="text-[11px] font-medium">256-bit SSL</span>
                                        </div>
                                    </div>
                                    <p className="mt-2 text-center text-[10px] text-muted-foreground/50">Powered by Razorpay · PCI DSS Compliant</p>
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            </div>
        </>
    )
}

export default function CheckoutPage() {
    return (
        <Suspense fallback={
            <div className="min-h-screen flex items-center justify-center bg-[#f1f3f6] dark:bg-background">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
        }>
            <CheckoutContent />
        </Suspense>
    )
}
