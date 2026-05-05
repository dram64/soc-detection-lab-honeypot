import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/components/**', 'src/routes/**', 'src/lib/**'],
      exclude: ['**/*.test.{ts,tsx}', '**/index.ts', '**/*.lazy.tsx'],
      thresholds: {
        // Lines/statements/branches are the meaningful gates. Functions sit
        // at 75% because chart components have Recharts SVG-render
        // callbacks (tooltip formatters, axis tick formatters, onClick on
        // virtualized rows) that jsdom can't invoke without layout. Their
        // *logic* is unit-tested in src/lib/format.test.ts (pure functions)
        // — what's uncovered is the Recharts wiring, exercised live in
        // npm run dev / npm run preview.
        lines: 80,
        functions: 75,
        statements: 80,
        branches: 70,
      },
    },
  },
});
