/**
 * Tailwind v4 uses CSS-first configuration: the design tokens, theme, and
 * dark-mode variant are declared directly in `src/globals.css` via `@theme`
 * and `@custom-variant`. This file is kept minimal for tooling/editor support
 * and to declare the content sources explicitly.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
}
