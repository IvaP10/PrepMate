const supportEmail = process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim()
const privacyEmail = process.env.NEXT_PUBLIC_PRIVACY_EMAIL?.trim()
const legalEmail = process.env.NEXT_PUBLIC_LEGAL_EMAIL?.trim()

function EmailLink({ address }: { address: string }) {
  return (
    <a className="font-medium text-primary underline-offset-4 hover:underline" href={`mailto:${address}`}>
      {address}
    </a>
  )
}

export function PublicContactDetails() {
  if (!supportEmail || !privacyEmail || !legalEmail) {
    return (
      <strong>
        Product support, privacy, and legal contact emails must be configured before launch.
      </strong>
    )
  }

  return (
    <>
      For product support, email <EmailLink address={supportEmail} />. For privacy requests, email{" "}
      <EmailLink address={privacyEmail} />. For legal notices, email <EmailLink address={legalEmail} />.
    </>
  )
}
