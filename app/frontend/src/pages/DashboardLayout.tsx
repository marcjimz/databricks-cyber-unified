import { Outlet } from "react-router-dom"
import { GenieDrawer } from "@/components/genie/genie-drawer"
import { GenieProvider } from "@/components/genie/genie-provider"
import { TopNav } from "@/components/shell/top-nav"
import { useConfig } from "@/config/ConfigProvider"

/**
 * Shell layout wrapping every dashboard route: top navigation, the Genie chat
 * provider + drawer (only when genie is enabled in config), and an <Outlet> for
 * the active page. Replaces the App-Router (dashboard)/layout.tsx.
 */
export function DashboardLayout() {
  const { config } = useConfig()

  const shell = (
    <div className="min-h-screen bg-background">
      <TopNav />
      <main className="mx-auto max-w-[1600px] px-4 py-8 sm:px-6 lg:px-8">
        <Outlet />
      </main>
      {config.features.genieEnabled ? <GenieDrawer /> : null}
    </div>
  )

  // Genie state (sessions, drawer) lives above the routed pages so chats persist
  // as the user navigates between domains.
  return config.features.genieEnabled ? (
    <GenieProvider>{shell}</GenieProvider>
  ) : (
    shell
  )
}
