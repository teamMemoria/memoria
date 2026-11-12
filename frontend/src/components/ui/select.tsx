// Adapted from shadcn/ui's MIT-licensed Select:
// https://ui.shadcn.com/r/styles/new-york/select.json
// Radix handles focus, typeahead, dismissal and selection; Memoria owns styling.
import type { ComponentProps, ReactNode } from 'react'
import * as SelectPrimitive from '@radix-ui/react-select'
import { Icon } from '../Icon'
import './select.css'

export const Select = SelectPrimitive.Root
export const SelectGroup = SelectPrimitive.Group
export function SelectValue(props: ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />
}

export function SelectTrigger({
  className = '', children, ...props
}: ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger className={`memoria-select-trigger ${className}`} {...props}>
      {children}
      <SelectPrimitive.Icon className="memoria-select-chevron">
        <Icon name="chevronDown" size={20} />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

export function SelectContent({
  className = '', children, position = 'popper', sideOffset = 8, ...props
}: ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        className={`memoria-select-content ${className}`}
        position={position}
        sideOffset={sideOffset}
        collisionPadding={12}
        {...props}
      >
        <SelectPrimitive.ScrollUpButton className="memoria-select-scroll memoria-select-scroll-up">
          <Icon name="chevronDown" />
        </SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="memoria-select-viewport">
          {children}
        </SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="memoria-select-scroll">
          <Icon name="chevronDown" />
        </SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

export function SelectItem({
  className = '', children, leading, description, ...props
}: ComponentProps<typeof SelectPrimitive.Item> & {
  leading?: ReactNode
  description?: string
}) {
  return (
    <SelectPrimitive.Item className={`memoria-select-item ${className}`} {...props}>
      {leading && <span className="memoria-select-leading" aria-hidden="true">{leading}</span>}
      <span className="memoria-select-copy">
        <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
        {description && <span className="memoria-select-description">{description}</span>}
      </span>
      <SelectPrimitive.ItemIndicator className="memoria-select-check">
        <Icon name="check" size={18} />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}

export function MemoriaSelectField({ id, label, value, onValueChange, options, disabled }: {
  id: string
  label: string
  value: string
  onValueChange: (value: string) => void
  options: readonly (readonly [string, string])[]
  disabled?: boolean
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectTrigger id={id} aria-label={label}><SelectValue /></SelectTrigger>
        <SelectContent>
          {options.map(([key, text]) => <SelectItem key={key} value={key}>{text}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  )
}
