// Demo signed-in user. In production this would come from the auth session.
const CURRENT_USER = {
  name: "Dana Whitfield",
  role: "CISO",
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("")
}

export function UserAvatar() {
  const user = CURRENT_USER
  return (
    <button
      type="button"
      title={`${user.name} · ${user.role}`}
      aria-label={`Signed in as ${user.name}, ${user.role}`}
      className="flex size-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground ring-2 ring-primary/20 transition-shadow hover:ring-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {initials(user.name)}
    </button>
  )
}
