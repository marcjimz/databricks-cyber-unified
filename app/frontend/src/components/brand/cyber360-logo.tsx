import { cn } from "@/lib/utils"

/**
 * Cyber360 brand mark.
 *
 * Uses the org logo: the full-color logo on light surfaces and the approved
 * one-color white logo on dark surfaces. Swap the assets in `public/` to
 * rebrand. Assets live in `public/` and are served from the site root, so
 * plain <img> tags with absolute paths work in both the Vite dev server and the
 * FastAPI-served production build.
 */
export function Cyber360Logo({
  className,
  showWordmark = true,
}: {
  className?: string
  showWordmark?: boolean
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      {/* Full-color logo for light backgrounds */}
      <img
        src="/org-logo-color.png"
        alt="Organization logo"
        className="h-8 w-auto dark:hidden"
        style={{ width: "auto" }}
      />
      {/* Full-color icon + white wordmark for dark backgrounds */}
      <img
        src="/org-logo-dark.png"
        alt="Organization logo"
        className="hidden h-8 w-auto dark:block"
        style={{ width: "auto" }}
      />
      {showWordmark ? (
        <>
          <span className="h-7 w-px bg-border" aria-hidden="true" />
          <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
            Cyber<span className="text-accent">Unified</span>
          </span>
        </>
      ) : null}
    </div>
  )
}
