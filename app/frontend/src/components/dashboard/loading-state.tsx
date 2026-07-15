import { cn } from "@/lib/utils"

export function LoadingGrid({
  count = 8,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8",
        className,
      )}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-xl border border-border bg-muted/50"
        />
      ))}
    </div>
  )
}

export function ErrorState({ message }: { message?: string }) {
  return (
    <div className="rounded-xl border border-danger/30 bg-danger-muted p-6 text-sm text-danger">
      {message ?? "Failed to load data from the metrics API."}
    </div>
  )
}
