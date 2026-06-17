import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        accent: '#4880FF',
        'accent-hover': '#3570E8',
        'wp-green': '#22c55e',
        'wp-red': '#ef4444',
        'wp-yellow': '#f59e0b',
        'wp-orange': '#f97316',
        'wp-purple': '#a855f7',
        'wp-muted': '#8E97A7',
        'bg-base': '#F5F6FA',
        'bg-card': '#ffffff',
        border: '#E8EAED',
        'text-base': '#1C2434',
      },
      fontFamily: {
        sans: ['IRANYekanX', 'sans-serif'],
      },
      borderRadius: {
        card: '12px',
      },
      boxShadow: {
        card: '0 1px 4px rgba(0,0,0,.06)',
      },
    },
  },
  plugins: [],
} satisfies Config
