import type { ComponentProps } from 'react'
import { Link } from 'react-router'
import { Icon } from './Icon'

export function BackLink({ children, className, ...props }: ComponentProps<typeof Link>) {
  return (
    <Link {...props} className={className ? `back-link inline-center ${className}` : 'back-link inline-center'}>
      <Icon name="arrowLeft" />
      {children}
    </Link>
  )
}
