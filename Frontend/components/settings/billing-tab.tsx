"use client"
import { useState, useEffect } from "react"
import { CreditCard, Download, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { fetchPaymentSubscription, fetchPaymentTransactions } from "@/lib/api"
import type { AuthUser } from "@/lib/auth"

const html = (value: unknown) =>
  String(value ?? "—").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!))

const invoiceMarkup = (txn: any) => {
  const date = txn.created_at ? new Date(txn.created_at).toLocaleDateString() : "—"
  const amount = `${txn.currency === "INR" ? "₹" : "$"}${txn.amount ?? "—"}`
  const rows = [
    ["Date", date],
    ["Amount", amount],
    ["Plan", txn.plan_type || "Free"],
    ["Status", txn.status || "pending"],
    ["Transaction ID", txn.transaction_id],
  ]

  return `<html><head><title>Invoice</title><style>body{font-family:system-ui;padding:40px;max-width:600px;margin:auto}h1{font-size:20px}table{width:100%;border-collapse:collapse;margin-top:24px}td,th{text-align:left;padding:8px 0;border-bottom:1px solid #eee;font-size:14px}</style></head><body><h1>InterAI Invoice</h1><table>${rows.map(([label, value]) => `<tr><th>${html(label)}</th><td>${html(value)}</td></tr>`).join("")}</table></body></html>`
}

export function BillingTab({ user, onOpenMembership }: { user?: AuthUser | null; onOpenMembership: () => void }) {
  const [transactions, setTransactions] = useState<any[]>([])
  const [subscription, setSubscription] = useState<any | null>(null)
  const [loadingTxn, setLoadingTxn] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [transactionResult, subscriptionResult] = await Promise.allSettled([
          fetchPaymentTransactions(20),
          fetchPaymentSubscription(),
        ])
        if (transactionResult.status === "fulfilled") {
          const data = transactionResult.value
          setTransactions(Array.isArray(data) ? data : data.transactions || [])
        }
        if (subscriptionResult.status === "fulfilled") setSubscription(subscriptionResult.value)
      } catch { }
      finally { setLoadingTxn(false) }
    }
    load()
  }, [])

  const planType = (user?.plan_type || "starter").toLowerCase()
  const planLabel = planType.includes("premium") ? "Premium" : planType.includes("pro") ? "Pro" : "Free"

  return (
    <div className="space-y-6">
      
      <div className="dashboard-card">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Current Plan</h3>
        <div className="sub-card flex flex-col items-stretch gap-4 rounded-lg sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-foreground">{planLabel}</p>
            {subscription?.is_signup_promo && (
              <div className={`mt-3 rounded-lg border px-3 py-2 text-xs leading-5 ${Number(subscription.days_remaining) <= 7 ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300" : "border-primary/20 bg-primary/5 text-primary"}`}>
                <p className="font-semibold">
                  {Number(subscription.days_remaining) <= 1
                    ? "Your free Premium access ends within 24 hours."
                    : `${subscription.days_remaining} days remain in your free Premium access.`}
                </p>
              </div>
            )}
          </div>
          <Button onClick={onOpenMembership} className="w-full shrink-0 gap-2 rounded-full shadow-sm sm:w-auto">
            <CreditCard className="h-4 w-4" /> View Plans
          </Button>
        </div>
      </div>

      
      <div className="dashboard-card">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Payment Method</h3>
        <div className="sub-card flex items-center justify-between rounded-lg border-dashed">
          <div>
            <p className="text-sm font-medium text-foreground">
              {transactions.find((txn: any) => txn.status === "completed" || txn.status === "success")?.payment_method || "Razorpay Checkout"}
            </p>
          </div>
        </div>
      </div>

      
      <div className="dashboard-card">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Billing History</h3>
        {loadingTxn ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading transactions" />
          </div>
        ) : transactions.length === 0 ? (
          <div className="sub-card flex flex-col items-center justify-center rounded-lg border-dashed py-12 text-center">
            <p className="text-sm font-medium text-foreground">No transactions yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Date</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Amount</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Plan</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Status</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">Invoice</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {transactions.map((txn: any, i: number) => (
                  <tr key={txn.transaction_id || i} className="transition-colors hover:bg-secondary/30">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-foreground">
                      {txn.created_at ? new Date(txn.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-foreground">
                      {txn.currency === "INR" ? "₹" : "$"}{txn.amount}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                        {txn.plan_type || txn.payment_method || "Free"}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${txn.status === "completed" || txn.status === "success" ? "bg-green-500/10 text-green-600 dark:text-green-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-400"}`}>
                        {txn.status || "pending"}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <Button variant="ghost" size="sm" className="gap-1.5 text-primary text-xs"
	                        onClick={() => {
	                          const w = window.open("", "_blank")
	                          if (!w) return
	                          w.document.write(invoiceMarkup(txn))
                          w.document.close()
                          w.print()
                        }}>
                        <Download className="h-3.5 w-3.5" /> Invoice
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
