import { Navigate, Outlet, Route, Routes, Link } from 'react-router'
import type { Viewer } from '../types/viewer'
import { AppLayout } from './layout/AppLayout'

function RouteMessage({ title, home }: { title: string; home: string }) {
  return (
    <>
      <h1>{title}</h1>
      <Link to={home}>Back to your conversations</Link>
    </>
  )
}

export function AppRoutes({ viewer }: { viewer: Viewer }) {
  const home = `/${viewer.role}/conversations`

  return (
    <Routes>
      <Route element={<AppLayout viewer={viewer} />}>
        <Route index element={<Navigate to={home} replace />} />
        <Route
          path="agent"
          element={
            viewer.role === 'agent' ? (
              <Outlet />
            ) : (
              <RouteMessage
                title="Page unavailable for your role"
                home={home}
              />
            )
          }
        >
          <Route index element={<Navigate to="conversations" replace />} />
          <Route path="conversations" element={<h1>My Conversations</h1>} />
          <Route path="knowledge" element={<h1>Knowledge Base</h1>} />
        </Route>
        <Route
          path="manager"
          element={
            viewer.role === 'manager' ? (
              <Outlet />
            ) : (
              <RouteMessage
                title="Page unavailable for your role"
                home={home}
              />
            )
          }
        >
          <Route index element={<Navigate to="conversations" replace />} />
          <Route path="conversations" element={<h1>Team conversations</h1>} />
          <Route path="knowledge" element={<h1>Knowledge drafts</h1>} />
        </Route>
        <Route
          path="*"
          element={<RouteMessage title="Page not found" home={home} />}
        />
      </Route>
    </Routes>
  )
}
