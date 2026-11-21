// Remembers the demo profile chosen on the entry screen across pages and
// refreshes. Storage can be unavailable (private windows, blocked site data),
// so every access is guarded and a failure just means choosing again.
const key = 'memoria.demoProfile'

export function loadSelectedProfile(): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function saveSelectedProfile(profileId: string) {
  try {
    localStorage.setItem(key, profileId)
  } catch {
    // Not remembered; the profile still applies until the page is reloaded.
  }
}

export function clearSelectedProfile() {
  try {
    localStorage.removeItem(key)
  } catch {
    // Nothing was stored.
  }
}
