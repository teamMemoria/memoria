import { useEntry } from './controller'
import { useId, useState } from 'react'
import { Button } from '../../components/controls'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select'
import type {
  DemoProfile,
  DemoProfilesApi,
  ViewerRole,
} from '../../types/viewer'
import './entry.css'

const roles: { value: ViewerRole; label: string }[] = [
  { value: 'agent', label: 'Agent' },
  { value: 'manager', label: 'Manager' },
]

function prefersReducedMotion() {
  return (
    typeof matchMedia === 'function' &&
    matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

// Demo sign-in: choose a role and a demo profile. Genesys handles real
// sign-in, so there are no passwords here.
export function EntryScreen({
  api,
  notice = null,
  onSelect,
}: {
  api: DemoProfilesApi
  notice?: string | null
  onSelect: (profile: DemoProfile) => void
}) {
  const [reducedMotion] = useState(prefersReducedMotion)
  const headingId = useId()
  const roleName = useId()
  const profileName = useId()
  const { state, role, setRole, setSelectedId, profiles, selected } = useEntry(api)

  return (
    <div className="entry">
      <main className="entry-panel grid-center grid-layout" aria-labelledby={headingId}>
        <div className="entry-panel-content">
          <header className="entry-welcome">
            <h1 id={headingId} aria-label="Welcome to Memoria">
              <span>Welcome to</span>
              <img src="/brand/memoria-wordmark-navy.svg" alt="" />
            </h1>
            <p className="entry-intro">Choose a demo profile to get started.</p>
          </header>
          {notice && (
            <p className="entry-notice" role="alert">
              {notice}
            </p>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (selected) onSelect(selected)
            }}
          >
            <fieldset className="entry-roles">
              <legend className="sr-only entry-sr-only">Sign in as</legend>
              {roles.map((item) => (
                <label key={item.value} className="entry-choice">
                  <input
                    aria-label={item.label}
                    type="radio"
                    name={roleName}
                    value={item.value}
                    checked={role === item.value}
                    onChange={() => {
                      setRole(item.value)
                      setSelectedId(null)
                    }}
                  />
                  <span className="entry-role-top" aria-hidden="true">
                    <img src={`/brand/login-${item.value}.svg`} alt="" />
                    {role === item.value && (
                      <img className="entry-role-selected" src="/brand/login-selected.svg" alt="" />
                    )}
                  </span>
                  <span className="entry-role-title">
                    {item.label}
                  </span>
                  <span className="entry-role-detail">
                    {item.value === 'agent' ? 'View your conversations' : 'Open manager workspace'}
                  </span>
                </label>
              ))}
            </fieldset>

            {state.status === 'loading' && (
              <p role="status">Loading demo profiles…</p>
            )}
            {state.status === 'error' && (
              <div className="entry-error">
                <p role="alert">We couldn't load the demo profiles.</p>
                <Button
                  variant="secondary"
                  onClick={state.retry}
                >
                  Try again
                </Button>
              </div>
            )}
            {state.status === 'ready' && profiles.length === 0 && (
              <p>No demo {role} profiles are available yet.</p>
            )}
            {state.status === 'ready' && profiles.length > 0 && (
              <div className="entry-profiles">
                <label htmlFor={profileName}>
                  {role === 'agent' ? 'Choose an agent' : 'Choose a manager'}
                </label>
                <Select value={selected?.id ?? ''} onValueChange={setSelectedId} required>
                  <SelectTrigger
                    id={profileName}
                    className="entry-profile-trigger"
                    aria-describedby={selected ? `${profileName}-detail` : undefined}
                  >
                    <span className="entry-avatar grid-center" aria-hidden="true">
                      {selected ? selected.displayName.slice(0, 2).toUpperCase() : '—'}
                    </span>
                    <SelectValue placeholder="Select a profile" />
                  </SelectTrigger>
                  <SelectContent>
                    {profiles.map((profile) => (
                      <SelectItem
                        key={profile.id}
                        value={profile.id}
                        textValue={profile.displayName}
                        leading={<span className="entry-avatar grid-center entry-avatar-small">{profile.displayName.slice(0, 2).toUpperCase()}</span>}
                        description={profile.conversationCount === null ? undefined :
                          `${profile.conversationCount} ${profile.conversationCount === 1 ? 'conversation' : 'conversations'}`}
                      >
                        {profile.displayName}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selected && (
                  <span id={`${profileName}-detail`} className="sr-only entry-sr-only">
                    Demo profile{selected.conversationCount !== null &&
                      ` (${selected.conversationCount} ${selected.conversationCount === 1 ? 'conversation' : 'conversations'})`}
                  </span>
                )}
              </div>
            )}

            <Button className="entry-continue" type="submit" disabled={!selected}>
              <span>{selected ? `Continue as ${selected.displayName}` : 'Continue'}</span>
            </Button>
          </form>
        </div>
      </main>

      <aside className="entry-brand grid-center" aria-label="Memoria">
        {reducedMotion ? (
          <img src="/brand/login-wordmark-white.svg" alt="Memoria" />
        ) : (
          <video
            src="/brand/memoria-login-navy.mp4"
            preload="auto"
            autoPlay
            muted
            playsInline
            aria-label="Memoria"
          />
        )}
      </aside>
    </div>
  )
}
