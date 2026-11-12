import { Outlet } from 'react-router'
import type { Viewer } from '../../types/viewer'
import { Sidebar } from './Sidebar'
import { ProfileMenu } from './ProfileMenu'
import './AppLayout.css'

export function AppLayout({
  viewer,
  onSwitchProfile,
}: {
  viewer: Viewer
  onSwitchProfile?: () => void
}) {
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
      <Sidebar viewer={viewer} onSwitchProfile={onSwitchProfile} />
      <div className="workspace">
        <header className="workspace-header">
          {onSwitchProfile ? (
            <ProfileMenu viewer={viewer} onSwitchProfile={onSwitchProfile}>
              <button className="avatar profile-trigger" type="button"
                aria-label={`Open profile menu for ${viewer.displayName}`}>
                <span role="img" aria-label={`${viewer.displayName}, ${viewer.role}`}>{initials}</span>
              </button>
            </ProfileMenu>
          ) : (
          <span
            className="avatar"
            role="img"
            aria-label={`${viewer.displayName}, ${viewer.role}`}
            title={viewer.displayName}
          >
            {initials}
          </span>
          )}
        </header>
        <main className="workspace-content" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
