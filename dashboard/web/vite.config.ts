import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, the API only allows CORS from https://dashboard.dram-soc.org.
// To avoid editing the production CORS config for development, the dev
// server proxies /api/* to the real API URL — same-origin from the
// browser's perspective. Production builds use VITE_API_BASE_URL
// directly (set at build time, e.g. via Phase 8 deploy environment).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget =
    env.VITE_API_BASE_URL || 'https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com';
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      target: 'es2022',
    },
  };
});
