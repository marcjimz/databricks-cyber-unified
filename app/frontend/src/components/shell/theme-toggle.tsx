import { Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/hooks/useTheme"

export function ThemeToggle() {
  const { isDark, toggleTheme } = useTheme()

  return (
    <Button
      variant="outline"
      size="icon"
      className="size-9 rounded-lg"
      aria-label="Toggle color theme"
      onClick={toggleTheme}
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  )
}
