import { Outlet } from 'react-router'
import type { Viewer } from '../../types/viewer'
import { Sidebar } from './Sidebar'
import './AppLayout.css'

export function AppLayout({ viewer }: { viewer: Viewer }) {
  const initials = viewer.displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar viewer={viewer} />
      <div className="workspace">
        <header className="workspace-header">
          <span
            className="avatar"
            role="img"
            aria-label={`${viewer.displayName}, ${viewer.role}`}
            title={viewer.displayName}
          >
            {initials}
          </span>
        </header>
        <main className="workspace-content" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
