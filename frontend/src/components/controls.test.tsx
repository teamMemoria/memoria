import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import {
  Button,
  Panel,
  SelectField,
  StatusLabel,
  Tabs,
  TextField,
} from './controls'

afterEach(cleanup)

describe('shared controls', () => {
  it('blocks activation while disabled or loading', () => {
    const onClick = vi.fn()
    const view = render(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    view.rerender(
      <Button loading loadingLabel="Saving…" onClick={onClick}>
        Save
      </Button>,
    )
    const button = screen.getByRole<HTMLButtonElement>('button', {
      name: 'Saving…',
    })
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('aria-busy')).toBe('true')
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('does not accidentally submit a form by default', () => {
    render(<Button>Open reference</Button>)
    expect(screen.getByRole<HTMLButtonElement>('button').type).toBe('button')
  })

  it('labels native fields and preserves their native events', () => {
    const onChange = vi.fn()
    render(
      <>
        <TextField
          id="search"
          label="Search calls"
          type="search"
          onChange={onChange}
        />
        <SelectField id="status" label="Review status" disabled>
          <option>All statuses</option>
        </SelectField>
      </>,
    )
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search calls' }), {
      target: { value: 'refund' },
    })
    expect(onChange).toHaveBeenCalledOnce()
    expect(
      screen.getByRole<HTMLSelectElement>('combobox', { name: 'Review status' })
        .disabled,
    ).toBe(true)
  })

  it('supports keyboard tabs and skips disabled items', () => {
    function Example() {
      const [value, setValue] = useState('pending')
      return (
        <Tabs
          label="Knowledge status"
          value={value}
          onChange={setValue}
          items={[
            { value: 'pending', label: 'Pending', content: 'Pending entries' },
            {
              value: 'flagged',
              label: 'Flagged',
              content: 'Flagged entries',
              disabled: true,
            },
            {
              value: 'approved',
              label: 'Approved',
              content: 'Approved entries',
            },
          ]}
        />
      )
    }
    render(<Example />)
    const pending = screen.getByRole('tab', { name: 'Pending' })
    const approved = screen.getByRole('tab', { name: 'Approved' })
    pending.focus()
    fireEvent.keyDown(pending, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(approved)
    expect(approved.getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel').textContent).toBe('Approved entries')
    expect(approved.getAttribute('aria-controls')).toBe(
      screen.getByRole('tabpanel').id,
    )
    fireEvent.keyDown(approved, { key: 'Home' })
    expect(document.activeElement).toBe(pending)
    fireEvent.keyDown(pending, { key: 'End' })
    expect(document.activeElement).toBe(approved)
    fireEvent.keyDown(approved, { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(pending)
  })

  it('names panels and keeps Cannot assess neutral', () => {
    render(
      <Panel title="Procedure">
        <StatusLabel>Cannot assess</StatusLabel>
      </Panel>,
    )
    expect(screen.getByRole('region', { name: 'Procedure' })).toBeTruthy()
    expect(screen.getByText('Cannot assess').className).toContain(
      'status-label--neutral',
    )
  })
})
