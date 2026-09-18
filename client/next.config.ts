import type { NextConfig } from 'next';
import { config } from 'dotenv';
import path from 'node:path';

config({ path: path.resolve(process.cwd(), '../.env'), quiet: true });
const backend = process.env.API_UPSTREAM_URL || 'http://127.0.0.1:8000';
const webOrigin = process.env.PRODUCTION_WEB_ORIGIN || '';
const configuredApiOrigin = process.env.PRODUCTION_API_ORIGIN || '';
const browserApiOrigin = (process.env.NEXT_PUBLIC_API_ORIGIN ||
  (configuredApiOrigin && configuredApiOrigin !== webOrigin ? configuredApiOrigin : '')).replace(/\/$/, '');
if (browserApiOrigin) {
  const parsed = new URL(browserApiOrigin);
  if (parsed.origin !== browserApiOrigin || (process.env.NODE_ENV === 'production' && parsed.protocol !== 'https:')) {
    throw new Error('NEXT_PUBLIC_API_ORIGIN must be an HTTPS origin without a path');
  }
}
process.env.NEXT_PUBLIC_API_ORIGIN = browserApiOrigin;
const development = process.env.NODE_ENV !== 'production';
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  `connect-src 'self' ${browserApiOrigin}${development ? ' ws: wss:' : ''}`,
  "img-src 'self' data:", "font-src 'self'", "object-src 'none'",
  "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
].join('; ');
const nextConfig: NextConfig = {
  agentRules: false,
  poweredByHeader: false,
  async rewrites() {
    return browserApiOrigin ? [] : ['/auth/:path*', '/v1/:path*'].map(source => ({source, destination: `${backend}${source}`}));
  },
  async headers() {
    return [{source: '/:path*', headers: [
      {key: 'X-Content-Type-Options', value: 'nosniff'},
      {key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin'},
      {key: 'X-Frame-Options', value: 'DENY'},
      {key: 'Content-Security-Policy', value: contentSecurityPolicy},
    ]}];
  },
};
export default nextConfig;
