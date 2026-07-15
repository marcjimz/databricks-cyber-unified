import { useCallback, useEffect, useState } from "react"

type Theme = "light" | "dark"

const STORAGE_KEY = "cyber360-theme"

function readInitialTheme(): Theme {
  if (typeof document !== "undefined" && document.documentElement.classList.contains("dark")) {
    return "dark"
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === "dark" || stored === "light") return stored
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark"
  }
  return "light"
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === "dark") root.classList.add("dark")
  else root.classList.remove("dark")
}

/**
 * Tiny theme store replacing `next-themes`: toggles a `class="dark"` on the
 * <html> element and persists the choice in localStorage. The initial class is
 * applied by an inline script in index.html to avoid a flash.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme)

  useEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const setTheme = useCallback((next: Theme) => setThemeState(next), [])
  const toggleTheme = useCallback(
    () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
    [],
  )

  return { theme, isDark: theme === "dark", setTheme, toggleTheme }
}
