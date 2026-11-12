import { useEffect, useId, useState } from 'react'
import { Button } from '../../components/controls'
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
        <h1 id={headingId}>Welcome to Memoria</h1>
        <p className="entry-intro">Choose a demo profile to open its dashboard.</p>
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
            <legend>Sign in as</legend>
            {roles.map((item) => (
              <label key={item.value} className="entry-choice">
                <input
                  type="radio"
                  name={roleName}
                  value={item.value}
                  checked={role === item.value}
                  onChange={() => {
                    setRole(item.value)
                    setSelectedId(null)
                  }}
                />
                {item.label}
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
            <fieldset className="entry-profiles">
              <legend>{role === 'agent' ? 'Agent profile' : 'Manager profile'}</legend>
              {profiles.map((profile) => (
                <label key={profile.id} className="entry-choice">
                  <input
                    type="radio"
                    name={profileName}
                    value={profile.id}
                    checked={selectedId === profile.id}
                    onChange={() => setSelectedId(profile.id)}
                  />
                  <span className="entry-profile-name">{profile.displayName}</span>
                  <span className="entry-profile-detail">
                    Demo profile
                    {profile.conversationCount !== null &&
                      ` · ${profile.conversationCount} ${
                        profile.conversationCount === 1
                          ? 'conversation'
                          : 'conversations'
                      }`}
                  </span>
                </label>
              ))}
            </fieldset>
          )}

          <Button type="submit" disabled={!selected}>
            Continue
          </Button>
        </form>
      </main>

      <aside className="entry-brand" aria-label="Memoria">
        {reducedMotion ? (
          <img src="/brand/memoria-wordmark.svg" alt="Memoria" />
        ) : (
          <video
            src="/brand/memoria-logo-animation.mp4"
            autoPlay
            muted
            loop
            playsInline
            aria-label="Memoria"
          />
        )}
      </aside>
    </div>
  )
}
