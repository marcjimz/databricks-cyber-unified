import { Navigate, Route, Routes } from "react-router-dom"
import { ConfigProvider, useConfig } from "@/config/ConfigProvider"
import { DashboardLayout } from "@/pages/DashboardLayout"
import { DomainPage } from "@/pages/DomainPage"
import { ManagerPage } from "@/pages/ManagerPage"
import { ScorecardPage } from "@/pages/ScorecardPage"
import { SocPage } from "@/pages/SocPage"

/**
 * The SOC analyst console is an optional persona view. It only mounts when the
 * `socViewEnabled` feature flag is set in `/api/config`; otherwise we redirect
 * to the scorecard so the route never 404s or renders an ungated persona.
 */
function SocRoute() {
  const { config } = useConfig()
  return config.features.socViewEnabled ? (
    <SocPage />
  ) : (
    <Navigate to="/scorecard" replace />
  )
}

/**
 * Client-side routing for the Cyber360 SPA (replaces the Next.js App Router).
 * All views hang off a single layout route that supplies the top nav, shell,
 * and Genie provider/drawer. Note the single generic `/domain/:key` route --
 * there are no per-domain pages, so adding a domain in cyber360.yaml requires
 * zero routing or page code (SKILL.md §3).
 */
export default function App() {
  return (
    <ConfigProvider>
      <Routes>
        <Route element={<DashboardLayout />}>
          <Route index element={<Navigate to="/scorecard" replace />} />
          <Route path="scorecard" element={<ScorecardPage />} />
          <Route path="manager" element={<ManagerPage />} />
          <Route path="soc" element={<SocRoute />} />
          <Route path="domain/:key" element={<DomainPage />} />
          <Route path="*" element={<Navigate to="/scorecard" replace />} />
        </Route>
      </Routes>
    </ConfigProvider>
  )
}
