import { useEffect, useId, useState } from 'react'
import { Button } from '../../components/controls'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select'
import type {
  DemoProfile,
  DemoProfilesApi,
  ViewerRole,
} from '../../types/viewer'
import './entry.css'

type ProfilesState =
  | { status: 'loading' }
  | { status: 'ready'; profiles: DemoProfile[] }
  | { status: 'error' }

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
  const [state, setState] = useState<ProfilesState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [role, setRole] = useState<ViewerRole>('agent')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reducedMotion] = useState(prefersReducedMotion)
  const headingId = useId()
  const roleName = useId()
  const profileName = useId()

  useEffect(() => {
    let active = true
    void api.listProfiles().then(
      (profiles) => {
        if (active) setState({ status: 'ready', profiles })
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, attempt])

  const profiles =
    state.status === 'ready'
      ? state.profiles.filter((profile) => profile.role === role)
      : []
  const selected = profiles.find((profile) => profile.id === selectedId)

  return (
    <div className="entry">
      <main className="entry-panel" aria-labelledby={headingId}>
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
              <legend className="entry-sr-only">Sign in as</legend>
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
                    {item.value === 'manager' && <img src="/brand/login-arrow.svg" alt="" />}
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
                  onClick={() => {
                    setState({ status: 'loading' })
                    setAttempt((value) => value + 1)
                  }}
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
                    <span className="entry-avatar" aria-hidden="true">
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
                        leading={<span className="entry-avatar entry-avatar-small">{profile.displayName.slice(0, 2).toUpperCase()}</span>}
                        description={profile.conversationCount === null ? undefined :
                          `${profile.conversationCount} ${profile.conversationCount === 1 ? 'conversation' : 'conversations'}`}
                      >
                        {profile.displayName}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selected && (
                  <span id={`${profileName}-detail`} className="entry-sr-only">
                    Demo profile{selected.conversationCount !== null &&
                      ` · ${selected.conversationCount} ${selected.conversationCount === 1 ? 'conversation' : 'conversations'}`}
                  </span>
                )}
              </div>
            )}

            <Button className="entry-continue" type="submit" disabled={!selected}>
              <span>{selected ? `Continue as ${selected.displayName}` : 'Continue'}</span>
              <img src="/brand/login-arrow.svg" alt="" />
            </Button>
          </form>
        </div>
      </main>

      <aside className="entry-brand" aria-label="Memoria">
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
