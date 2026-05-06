"use client"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { CreditCard, Check, X, Download, Loader2, Receipt } from "lucide-react"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { fetchPaymentTransactions } from "@/lib/api"
import type { AuthUser } from "@/lib/auth"

const html = (value: unknown) =>
  String(value ?? "—").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!))

const invoiceMarkup = (txn: any) => {
  const date = txn.created_at ? new Date(txn.created_at).toLocaleDateString() : "—"
  const amount = `${txn.currency === "INR" ? "₹" : "$"}${txn.amount ?? "—"}`
  const rows = [
    ["Date", date],
    ["Amount", amount],
    ["Plan", txn.plan_type || "Starter"],
    ["Status", txn.status || "pending"],
    ["Transaction ID", txn.transaction_id],
  ]

  return `<html><head><title>Invoice</title><style>body{font-family:system-ui;padding:40px;max-width:600px;margin:auto}h1{font-size:20px}table{width:100%;border-collapse:collapse;margin-top:24px}td,th{text-align:left;padding:8px 0;border-bottom:1px solid #eee;font-size:14px}</style></head><body><h1>InterAI Invoice</h1><table>${rows.map(([label, value]) => `<tr><th>${html(label)}</th><td>${html(value)}</td></tr>`).join("")}</table></body></html>`
}

export function BillingTab({ user, onOpenMembership }: { user?: AuthUser | null; onOpenMembership: () => void }) {
  const router = useRouter()
  const [transactions, setTransactions] = useState<any[]>([])
  const [loadingTxn, setLoadingTxn] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchPaymentTransactions(20)
        setTransactions(Array.isArray(data) ? data : data.transactions || [])
      } catch { }
      finally { setLoadingTxn(false) }
    }
    load()
  }, [])

  const planLabel = user?.interviews_remaining === 0 ? "Free" : "Active Plan"

  return (
    <div className="space-y-6">
      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Current Plan</h3>
        <p className="mb-4 text-xs text-muted-foreground">Manage your subscription and plan.</p>
        <div className="flex items-center justify-between rounded-lg border border-border bg-secondary/30 p-4">
          <div>
            <p className="font-semibold text-foreground">{planLabel}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {user?.interviews_remaining !== undefined
                ? `${user.interviews_remaining} interview${user.interviews_remaining === 1 ? "" : "s"} remaining`
                : "Cancel anytime. No contracts."}
            </p>
          </div>
          <Button onClick={onOpenMembership} className="gap-2 rounded-full shadow-sm">
            <CreditCard className="h-4 w-4" /> View Plans
          </Button>
        </div>
      </div>

      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Payment Method</h3>
        <p className="mb-4 text-xs text-muted-foreground">Your saved payment details.</p>
        <div className="flex items-center justify-between rounded-lg border border-dashed border-border/70 bg-secondary/20 p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-card ring-1 ring-border/50">
              <CreditCard className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">No payment method on file</p>
              <p className="text-xs text-muted-foreground">Add one when you purchase a plan.</p>
            </div>
          </div>
        </div>
      </div>

      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <div className="mb-4 flex items-center gap-2">
          <Receipt className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold text-foreground">Billing History</h3>
        </div>
        {loadingTxn ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading transactions...</span>
          </div>
        ) : transactions.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/70 bg-secondary/20 py-12 text-center">
            <Receipt className="mb-2 h-7 w-7 text-muted-foreground/50" />
            <p className="text-sm font-medium text-foreground">No transactions yet</p>
            <p className="mt-1 text-xs text-muted-foreground">Your billing history will appear here after your first purchase.</p>
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
                        {txn.plan_type || txn.payment_method || "Starter"}
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
