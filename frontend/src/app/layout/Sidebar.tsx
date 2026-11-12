import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router'
import type { Viewer } from '../../types/viewer'
import { ProfileMenu } from './ProfileMenu'
import { Icon } from '../../components/Icon'
import { createSidebarMotion } from './sidebarMotion.js'

export function Sidebar({ viewer, onSwitchProfile }: { viewer: Viewer; onSwitchProfile?: () => void }) {
  const profileMenuOpen = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const sidebar = useRef<HTMLElement>(null)
  const brand = useRef<HTMLAnchorElement>(null)
  const logo = useRef<HTMLSpanElement>(null)
  const motion = useRef<ReturnType<typeof createSidebarMotion> | null>(null)
  const logoId = useId()
  const restoringFocus = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pointerInside = useRef(false)
  const keyboardInside = useRef(false)
  const base = `/${viewer.role}`
  const navigation = [
    {
      page: 'conversations',
      label: viewer.role === 'agent' ? 'Conversations' : 'Team conversations',
    },
    { page: 'knowledge', label: 'Knowledge Base' },
  ] as const

  function open() {
    clearTimeout(timer.current)
    setExpanded(true)
  }

  function scheduleClose() {
    clearTimeout(timer.current)
    if (!profileMenuOpen.current && !pointerInside.current && !keyboardInside.current) {
      timer.current = setTimeout(() => setExpanded(false), 100)
    }
  }

  useLayoutEffect(() => {
    if (!sidebar.current || !logo.current) return
    const controller = createSidebarMotion(
      sidebar.current,
      logo.current,
      logoId,
    )
    motion.current = controller
    return () => {
      controller.destroy()
      motion.current = null
    }
  }, [logoId])

  useEffect(() => {
    motion.current?.setExpanded(expanded)
  }, [expanded])

  useEffect(() => {
    function dismiss(event: KeyboardEvent | PointerEvent) {
      if (profileMenuOpen.current) return
      const escape = event instanceof KeyboardEvent && event.key === 'Escape'
      // A portalled menu owns Escape and restores focus to its trigger.
      if (escape && event.target instanceof Element && event.target.closest('[role="menu"]')) return
      const outside =
        event.type === 'pointerdown' &&
        event.target instanceof Node &&
        !sidebar.current?.contains(event.target)
      if (escape || outside) {
        clearTimeout(timer.current)
        if (escape && sidebar.current?.contains(document.activeElement)) {
          event.preventDefault()
          restoringFocus.current = true
          brand.current?.focus({ preventScroll: true })
          restoringFocus.current = false
        }
        setExpanded(false)
      }
    }

    function dismissOnBlur() {
      clearTimeout(timer.current)
      pointerInside.current = false
      keyboardInside.current = false
      setExpanded(false)
    }

    document.addEventListener('keydown', dismiss)
    document.addEventListener('pointerdown', dismiss)
    window.addEventListener('blur', dismissOnBlur)
    return () => {
      clearTimeout(timer.current)
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('pointerdown', dismiss)
      window.removeEventListener('blur', dismissOnBlur)
    }
  }, [])

  return (
    <aside
      ref={sidebar}
      className="sidebar"
      aria-label="Navigation"
      data-expanded={expanded}
      onPointerEnter={(event) => {
        if (event.pointerType === 'touch') return
        if (
          typeof matchMedia === 'function' &&
          !matchMedia('(hover: hover) and (pointer: fine)').matches
        )
          return
        if (event.buttons) return
        pointerInside.current = true
        clearTimeout(timer.current)
        if (motion.current && !motion.current.isCollapsed()) open()
        else timer.current = setTimeout(() => setExpanded(true), 100)
      }}
      onPointerLeave={() => {
        pointerInside.current = false
        scheduleClose()
      }}
      onPointerDownCapture={() => {
        keyboardInside.current = false
        open()
      }}
      onFocusCapture={(event) => {
        if (!restoringFocus.current && event.target.matches(':focus-visible')) {
          keyboardInside.current = true
          open()
        }
      }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          keyboardInside.current = false
          scheduleClose()
        }
      }}
    >
      <Link
        ref={brand}
        className="sidebar-brand"
        to={`${base}/conversations`}
        aria-label="Memoria home"
        aria-expanded={expanded}
        aria-controls="primary-navigation"
      >
        <span ref={logo} className="sidebar-logo" aria-hidden="true" />
      </Link>
      <nav id="primary-navigation" aria-label="Main navigation">
        <span className="sidebar-selection" aria-hidden="true" />
        {navigation.map(({ page, label }) => (
          <NavLink
            key={page}
            className="sidebar-item"
            to={`${base}/${page}`}
            aria-label={label}
            title={label}
          >
            <Icon name={page} size={25} />
            <span className="sidebar-label" aria-hidden="true">
              {label}
            </span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        {onSwitchProfile ? (
          <ProfileMenu viewer={viewer} onSwitchProfile={onSwitchProfile} side="right"
            onOpenChange={(isOpen) => {
              profileMenuOpen.current = isOpen
              if (isOpen) open()
              else scheduleClose()
            }}>
            <button className="sidebar-item profile-trigger" type="button"
              aria-label={`Open profile menu for ${viewer.displayName}`}>
              <Icon name="account" size={25} />
              <span className="sidebar-label" aria-hidden="true">{viewer.displayName}</span>
            </button>
          </ProfileMenu>
        ) : (
        <span
          className="sidebar-item"
          role="img"
          aria-label={viewer.displayName}
          title={viewer.displayName}
        >
          <Icon name="account" size={25} />
          <span className="sidebar-label" aria-hidden="true">
            {viewer.displayName}
          </span>
        </span>
        )}
      </div>
    </aside>
  )
}
