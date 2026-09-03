import type { NextConfig } from 'next';

const publicBasePath =
  process.env.NEXT_PUBLIC_BASE_PATH?.trim().replace(/\/+$/, '') || '';

const nextConfig: NextConfig = {
  output: 'export',
  trailingSlash: false,
  assetPrefix: publicBasePath ? `${publicBasePath}/` : undefined,
};

export default nextConfig;
