import { ChevronRight } from "lucide-react"
import { Link } from "react-router-dom"

export interface Crumb {
  label: string
  href?: string
}

/**
 * Breadcrumb ribbon shown at the top of drill-down pages so users always know
 * where they are in the navigation hierarchy (e.g. Scorecard → Domain).
 */
export function DrillBreadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm">
        {items.map((item, i) => {
          const last = i === items.length - 1
          return (
            <li key={item.label} className="flex items-center gap-1.5">
              {item.href && !last ? (
                <Link
                  to={item.href}
                  className="font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? "page" : undefined}
                  className={
                    last
                      ? "font-semibold text-foreground"
                      : "font-medium text-muted-foreground"
                  }
                >
                  {item.label}
                </span>
              )}
              {!last ? (
                <ChevronRight className="size-3.5 text-muted-foreground/50" />
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
