import { MessageSquareText } from "lucide-react"
import type { ReactNode } from "react"
import { useGenie } from "@/components/genie/genie-provider"
import { Button } from "@/components/ui/button"
import type { GenieDomainKey } from "@/lib/genie/config"

/**
 * Thin wrapper for a domain drill-down: renders the page content and a
 * "Chat on this Data" trigger that opens the global Genie drawer scoped to
 * this domain. Chat history lives in GenieProvider, so conversations carry
 * over as the user moves between domains.
 */
export function GenieChatDock({
  domainKey,
  children,
}: {
  domainKey: GenieDomainKey
  children: ReactNode
}) {
  const { openForDomain } = useGenie()

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <Button
          type="button"
          onClick={() => openForDomain(domainKey)}
          aria-controls="genie-chat-panel"
          className="gap-2"
        >
          <MessageSquareText className="size-4" />
          Chat on this Data
        </Button>
      </div>

      {children}
    </div>
  )
}
