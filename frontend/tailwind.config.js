/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: '#050505',
        foreground: '#EDEDED',
        card: {
          DEFAULT: '#0A0A0A',
          foreground: '#EDEDED'
        },
        popover: {
          DEFAULT: '#0A0A0A',
          foreground: '#EDEDED'
        },
        primary: {
          DEFAULT: '#2962FF',
          foreground: '#FFFFFF'
        },
        secondary: {
          DEFAULT: '#A1A1AA',
          foreground: '#EDEDED'
        },
        muted: {
          DEFAULT: '#121212',
          foreground: '#52525B'
        },
        accent: {
          DEFAULT: '#00FF94',
          foreground: '#050505'
        },
        destructive: {
          DEFAULT: '#FF0055',
          foreground: '#FFFFFF'
        },
        border: '#27272A',
        input: '#27272A',
        ring: '#2962FF',
        buy: '#00FF94',
        sell: '#FF0055'
      },
      fontFamily: {
        heading: ['Unbounded', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace']
      },
      borderRadius: {
        lg: '0.5rem',
        md: '0.375rem',
        sm: '0.25rem'
      },
      boxShadow: {
        'neon-blue': '0 0 20px -5px rgba(41, 98, 255, 0.3)',
        'neon-green': '0 0 20px -5px rgba(0, 255, 148, 0.3)',
        'neon-red': '0 0 20px -5px rgba(255, 0, 85, 0.3)'
      },
      animation: {
        'trace': 'trace 2s ease-in-out infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite'
      },
      keyframes: {
        trace: {
          '0%, 100%': { borderColor: '#27272A' },
          '50%': { borderColor: '#2962FF' }
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 5px currentColor' },
          '50%': { boxShadow: '0 0 20px currentColor' }
        }
      }
    }
  },
  plugins: [require("tailwindcss-animate")]
};