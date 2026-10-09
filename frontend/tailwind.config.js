/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), muted: v("muted"), border: v("border"),
        fg: v("fg"), subtle: v("subtle"), primary: v("primary"), "primary-fg": v("primary-fg"),
        ok: v("ok"), watch: v("watch"), warn: v("warn"), danger: v("danger"), unknown: v("unknown"),
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
    },
  },
  plugins: [],
};
