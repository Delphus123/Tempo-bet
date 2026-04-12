/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0a',
        card: '#1a1a2e',
        border: '#16213e',
        primary: '#00b4d8',
        success: '#00ff88',
        warn: '#ff8c00',
        highlight: '#ffd60a',
        muted: '#6c757d',
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
};
