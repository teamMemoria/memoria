import type { ReactElement } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import type { Viewer } from '../../types/viewer'

export function ProfileMenu({ viewer, onSwitchProfile, onOpenChange, children, side = 'bottom' }: {
  viewer: Viewer
  onSwitchProfile: () => void
  onOpenChange?: (open: boolean) => void
  children: ReactElement
  side?: 'bottom' | 'right'
}) {
  return (
    <DropdownMenu.Root modal={false} onOpenChange={onOpenChange}>
      <DropdownMenu.Trigger asChild>{children}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="profile-menu"
          side={side}
          align="end"
          sideOffset={8}
          collisionPadding={12}
          aria-label={`Profile for ${viewer.displayName}`}
        >
          <DropdownMenu.Label className="profile-menu-label">
            <strong>{viewer.displayName}</strong>
            <span>{viewer.role === 'agent' ? 'Agent' : 'Manager'}</span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="profile-menu-separator" />
          <DropdownMenu.Item className="profile-menu-item" onSelect={onSwitchProfile}>
            Switch profile
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
