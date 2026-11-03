export function createSidebarMotion(
  sidebar: HTMLElement,
  logoHost: HTMLElement,
  id: string,
): {
  setExpanded(expanded: boolean): void
  isCollapsed(): boolean
  destroy(): void
}
