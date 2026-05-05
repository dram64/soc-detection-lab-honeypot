/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dashboard palette — dark theme, teal accent (per Phase 5 brief).
        // Phase 6 will iterate on this once real visualizations land.
        bg: {
          DEFAULT: '#0b0f14', // near-black neutral, page background
          elevated: '#121821', // slightly raised surfaces (cards)
          border: '#1f2933', // subtle dividers
        },
        fg: {
          DEFAULT: '#e6edf3', // high-contrast off-white
          muted: '#8b96a3', // secondary copy
          subtle: '#5a6473', // tertiary / placeholder
        },
        accent: {
          DEFAULT: '#2dd4bf', // teal — Z's preferred color
          dim: '#0f766e',
        },
        danger: {
          DEFAULT: '#f87171',
          dim: '#7f1d1d',
        },
        ok: {
          DEFAULT: '#34d399',
        },
      },
      fontFamily: {
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
};
