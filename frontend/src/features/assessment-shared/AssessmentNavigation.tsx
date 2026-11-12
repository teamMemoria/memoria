import { useLayoutEffect, useRef } from 'react'
import { NavLink } from 'react-router'
import { categories } from './assessment'
import type { CallReview } from '../../types/callReview'

function positionSelection(navigation: HTMLElement) {
  const link = navigation.querySelector<HTMLAnchorElement>(
    '[aria-current="page"]',
  )
  if (!link) return
  navigation.style.setProperty('--selection-left', `${link.offsetLeft}px`)
  navigation.style.setProperty('--selection-width', `${link.offsetWidth}px`)
  navigation.style.setProperty('--selection-height', `${link.offsetHeight}px`)
  navigation.dataset.ready = 'true'
  return link
}

function revealSelection(
  navigation: HTMLElement,
  link: HTMLElement,
  animate: boolean,
) {
  const left = link.offsetLeft - 4
  const right = link.offsetLeft + link.offsetWidth + 4
  const target =
    left < navigation.scrollLeft
      ? left
      : right > navigation.scrollLeft + navigation.clientWidth
        ? right - navigation.clientWidth
        : navigation.scrollLeft
  if (target !== navigation.scrollLeft) {
    navigation.scrollTo({
      left: Math.max(0, target),
      behavior: animate ? 'smooth' : 'instant',
    })
  }
}

export function AssessmentNavigation({
  metric,
  base,
  search,
  call,
}: {
  metric: string
  base: string
  search: string
  call: CallReview
}) {
  const navigation = useRef<HTMLElement>(null)

  useLayoutEffect(() => {
    const element = navigation.current!
    const animate =
      element.dataset.ready === 'true' &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const link = positionSelection(element)
    if (link) revealSelection(element, link, animate)
  }, [metric])

  useLayoutEffect(() => {
    const element = navigation.current!
    let disposed = false
    const update = () => {
      if (disposed) return
      const link = positionSelection(element)
      if (link) revealSelection(element, link, false)
    }
    const observer = new ResizeObserver(update)
    observer.observe(element)
    element.querySelectorAll('a').forEach((link) => observer.observe(link))
    void document.fonts?.ready.then(update)
    return () => {
      disposed = true
      observer.disconnect()
    }
  }, [])

  return (
    <nav
      ref={navigation}
      className="metric-navigation"
      aria-label="Assessment categories"
    >
      <span className="metric-selection" aria-hidden="true" />
      {categories.map((item, index) => {
        const result = call.criteria.find(
          (criterion) => criterion.id === item.id,
        )?.result
        return (
          <NavLink key={item.id} to={`${base}/assessments/${item.id}${search}`}>
            <span className="metric-number" aria-hidden="true">
              0{index + 1}
            </span>
            {item.title}
            <span
              className={`metric-dot metric-dot--${result ?? 'unavailable'}`}
              aria-hidden="true"
            />
          </NavLink>
        )
      })}
    </nav>
  )
}
