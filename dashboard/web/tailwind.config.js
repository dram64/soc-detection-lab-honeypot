/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dashboard palette — dark neutral surfaces, urban-yellow accent
        // with a magenta secondary for warning flavoring. Inkier than the
        // prior teal scheme; meant to read as industrial/utility chrome
        // rather than tasteful admin pastel.
        bg: {
          DEFAULT: '#08090d', // ink-black page background
          elevated: '#10141b', // slightly raised surfaces (cards)
          border: '#222a36', // subtle dividers
          edge: '#3a4554', // stronger dividers for emphasis
        },
        fg: {
          DEFAULT: '#eef1f5', // off-white, slightly cooler than before
          muted: '#8d97a4', // secondary copy
          subtle: '#5a6473', // tertiary / placeholder
        },
        accent: {
          DEFAULT: '#f5d11f', // urban yellow — primary highlight color
          dim: '#736216', // muted yellow for hover/secondary states
        },
        accent2: {
          DEFAULT: '#ec4899', // magenta — secondary accent for warnings
          dim: '#831843',
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
        // Display face for the masthead — chunky condensed sans-serif.
        // Falls back gracefully when Bebas Neue isn't loaded.
        display: [
          '"Bebas Neue"',
          '"Oswald"',
          '"Arial Narrow"',
          'Impact',
          'sans-serif',
        ],
      },
      letterSpacing: {
        widest: '0.18em',
      },
    },
  },
  plugins: [],
};
