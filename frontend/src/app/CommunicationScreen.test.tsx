import { it, expect } from 'vitest'
import { fireEvent, screen, within, openCategory, scoredCall } from './AssessmentTestSupport'
it('selects canonical wording turns without presenting the text graphic as recorded audio', async () => {
    const call = await scoredCall('communication-style')
    await openCategory('communication-style', call)
    const turn = call.transcript!.turns.find((item) => item.number === 8)!
    fireEvent.click(screen.getByRole('button', { name: /View turn 8, Agent,/ }))
    const preview = screen.getByRole('region', {
      name: 'Selected transcript turn',
    })
    expect(preview.textContent).toContain(turn.text)
    expect(
      screen
        .getByRole('button', { name: 'Enable demo voice' })
        .hasAttribute('disabled'),
    ).toBe(true)
    expect(screen.queryByText('Voice settings')).toBeNull()
    expect(screen.queryByText(/Generated speech from masked text/)).toBeNull()
    expect(document.querySelectorAll('.waveform-turn').length).toBe(
      call.transcript!.turns.length,
    )
    fireEvent.click(
      within(preview).getByRole('button', { name: 'View context' }),
    )
    expect((await screen.findByRole('dialog')).textContent).toContain(turn.text)
  })

it('keeps unavailable scores neutral and wording excerpts tied to recorded checks', async () => {
    const call = await scoredCall('communication-style')
    call.criteria[0].scoring!.score = null
    call.criteria[0].scoring!.checks[0].outcome = 'unresolved'
    call.criteria[0].scoring!.checks[0].critical = false
    await openCategory('communication-style', call)
    expect(document.querySelector('.gauge-value')).toBeNull()
    expect(screen.getByText('No assessed Agent wording supplied.')).toBeTruthy()
    expect(document.querySelector('audio')).toBeNull()
    expect(screen.getByText('No assessed phrases available.')).toBeTruthy()
    expect(screen.queryByText('Checks met')).toBeNull()
  })
