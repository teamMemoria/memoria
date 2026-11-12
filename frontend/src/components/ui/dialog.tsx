// Adapted from shadcn/ui. MIT licence: /licenses/shadcn-ui-LICENSE.txt.
import type { ComponentProps } from 'react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { Icon } from '../Icon'
import './dialog.css'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogTitle = DialogPrimitive.Title
export const DialogDescription = DialogPrimitive.Description

export function DialogContent({
  children,
  className = '',
  ...props
}: ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="ui-dialog-overlay" />
      <DialogPrimitive.Content
        {...props}
        className={`ui-dialog-content ${className}`}
      >
        {children}
        <DialogPrimitive.Close className="ui-dialog-close" aria-label="Close">
          <Icon name="close" size={20} />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
