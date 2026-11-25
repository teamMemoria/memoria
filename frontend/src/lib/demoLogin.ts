/**
 * Whether this build offers the demo profiles and sends the chosen one as
 * X-Dev-User. Always on in development. A production build only turns it on
 * when it is built with VITE_DEMO_LOGIN=true, as the hosted school demo is:
 * anyone with the link can pick a demo profile. The backend must also be
 * configured to accept X-Dev-User, and still checks every permission.
 */
export function demoLoginEnabled(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_DEMO_LOGIN === 'true'
}

export function demoScorecardsEnabled(): boolean {
  return import.meta.env.MODE === 'simulation' ||
    (demoLoginEnabled() && import.meta.env.VITE_HOSTED_DEMO_SCORECARDS === 'true')
}
