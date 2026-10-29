import type { ReactNode } from 'react'
import { Button } from './Button'
import { Dialog } from './Dialog'

/** Confirmation for destructive operations; the confirm button names the action instead of saying "OK". */
export function ConfirmDialog({ title, children, confirmLabel, onConfirm, onCancel }: { title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Dialog title={title} onClose={onCancel} footer={<><Button onClick={onCancel}>Cancel</Button><Button variant="destructive" onClick={onConfirm}>{confirmLabel}</Button></>}>
      {children}
    </Dialog>
  )
}
