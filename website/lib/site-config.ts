const publicBasePath =
  process.env.NEXT_PUBLIC_BASE_PATH?.trim().replace(/\/+$/, '') || '';

function publicPath(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${publicBasePath}${normalizedPath}`;
}

export const siteConfig = Object.freeze({
  productName: "PrepMate",
  publicBasePath,
  publicPath,
  manifestUrl:
    process.env.NEXT_PUBLIC_PREPMATE_RELEASE_MANIFEST_URL?.trim() ||
    publicPath("/latest.json"),
  supportEmail:
    process.env.NEXT_PUBLIC_PREPMATE_SUPPORT_EMAIL?.trim() ||
    "support@example.invalid",
  securityEmail:
    process.env.NEXT_PUBLIC_PREPMATE_SECURITY_EMAIL?.trim() ||
    "security@example.invalid",
});
