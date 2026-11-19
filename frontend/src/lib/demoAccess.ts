export function demoProfilesEnabled() {
  return import.meta.env.DEV || import.meta.env.VITE_PUBLIC_DEMO === 'true'
}
