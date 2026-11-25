import type { ComponentProps } from 'react'

export function Card({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="card" className={className} {...props} />
}
