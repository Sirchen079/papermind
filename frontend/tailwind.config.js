/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      borderRadius: { md: 'var(--radius-sm)', lg: 'var(--radius-md)', xl: 'var(--radius-lg)', '2xl': 'var(--radius-lg)', '3xl': 'var(--radius-lg)' },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ['var(--font-mono)'],
      },
    },
  },
  plugins: [],
};
