// Adapted from shadcn/ui. MIT licence: /licenses/shadcn-ui-LICENSE.txt.
import type { ComponentProps } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Icon } from '../Icon'
import './dialog.css'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
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
        className={`ui-dialog-content panel-frame ${className}`}
      >
        {children}
        <DialogPrimitive.Close className="ui-dialog-close grid-center" aria-label="Close">
          <Icon name="close" size={20} />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
