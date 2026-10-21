import { useId, type ComponentProps, type ReactNode } from 'react'
import { Icon } from './Icon'

type ButtonProps = ComponentProps<'button'> & {
  variant?: 'primary' | 'secondary' | 'quiet'
  loading?: boolean
  loadingLabel?: string
}

export function Button({
  variant = 'primary',
  loading = false,
  loadingLabel = 'Loading…',
  disabled,
  className = '',
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      className={`button button--${variant} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? loadingLabel : children}
    </button>
  )
}

type TextFieldProps = ComponentProps<'input'> & { id: string; label: string }

export function TextField({
  id,
  label,
  type = 'text',
  className = '',
  ...props
}: TextFieldProps) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <span
        className={`field-input ${type === 'search' ? 'field-input--search' : ''}`}
      >
        {type === 'search' && <Icon name="search" />}
        <input
          {...props}
          id={id}
          type={type}
          className={`control-input ${className}`}
        />
      </span>
    </label>
  )
}

type SelectFieldProps = ComponentProps<'select'> & { id: string; label: string }

export function SelectField({
  id,
  label,
  className = '',
  children,
  ...props
}: SelectFieldProps) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <span className="field-input">
        <select {...props} id={id} className={`control-input ${className}`}>
          {children}
        </select>
        <Icon name="chevronDown" />
      </span>
    </label>
  )
}

type Tab = {
  value: string
  label: string
  content: ReactNode
  disabled?: boolean
}

export function Tabs({
  label,
  items,
  value,
  onChange,
}: {
  label: string
  items: readonly Tab[]
  value: string
  onChange: (value: string) => void
}) {
  const id = useId()
  const selected = items.find((item) => item.value === value)
  const available = items.filter((item) => !item.disabled)

  return (
    <div className="tabs">
      <div className="tab-list" role="tablist" aria-label={label}>
        {items.map((item) => (
          <button
            key={item.value}
            id={`${id}-tab-${item.value}`}
            className="tab"
            type="button"
            role="tab"
            aria-selected={item.value === value}
            aria-controls={`${id}-panel`}
            tabIndex={item.value === value ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.value)}
            onKeyDown={(event) => {
              if (
                !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(
                  event.key,
                ) ||
                !available.length
              )
                return
              event.preventDefault()
              const index = available.findIndex(
                (tab) => tab.value === item.value,
              )
              const nextIndex =
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? available.length - 1
                    : (index +
                        (event.key === 'ArrowRight' ? 1 : -1) +
                        available.length) %
                      available.length
              onChange(available[nextIndex].value)
              event.currentTarget
                .closest('[role="tablist"]')
                ?.querySelectorAll<HTMLButtonElement>(
                  '[role="tab"]:not(:disabled)',
                )
                [nextIndex]?.focus()
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      {selected && (
        <div
          role="tabpanel"
          id={`${id}-panel`}
          aria-labelledby={`${id}-tab-${selected.value}`}
          tabIndex={0}
        >
          {selected.content}
        </div>
      )}
    </div>
  )
}

export function Panel({
  title,
  className = '',
  children,
  ...props
}: ComponentProps<'section'> & { title: string }) {
  const headingId = useId()
  return (
    <section
      {...props}
      className={`panel ${className}`}
      aria-labelledby={headingId}
    >
      <h2 id={headingId}>{title}</h2>
      {children}
    </section>
  )
}

export function StatusLabel({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'positive' | 'attention'
  children: ReactNode
}) {
  return (
    <span className={`status-label status-label--${tone}`}>
      <span className="status-dot" aria-hidden="true" />
      {children}
    </span>
  )
}
