import * as React from 'react'
import { cn } from 'cn'
import { Dialog as SheetPrimitive } from 'radix-ui'

// shadcn/ui Sheet, styled with Memoria's CSS instead of a global Tailwind reset.
function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root {...props} />
}

function SheetClose(props: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetContent({ className, children, ...props }: React.ComponentProps<typeof SheetPrimitive.Content>) {
  return <SheetPrimitive.Portal>
    <SheetPrimitive.Overlay data-slot="sheet-overlay" />
    <SheetPrimitive.Content data-slot="sheet-content" className={cn('evidence-sheet', className)} {...props}>
      {children}
      <SheetClose className="close-dialog" aria-label="Close evidence">×</SheetClose>
    </SheetPrimitive.Content>
  </SheetPrimitive.Portal>
}

function SheetHeader(props: React.ComponentProps<'div'>) {
  return <div data-slot="sheet-header" {...props} />
}

function SheetFooter(props: React.ComponentProps<'div'>) {
  return <div data-slot="sheet-footer" {...props} />
}

function SheetTitle(props: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return <SheetPrimitive.Title data-slot="sheet-title" {...props} />
}

function SheetDescription(props: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return <SheetPrimitive.Description data-slot="sheet-description" {...props} />
}

export { Sheet, SheetClose, SheetContent, SheetHeader, SheetFooter, SheetTitle, SheetDescription }
