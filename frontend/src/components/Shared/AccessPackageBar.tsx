import { useState } from 'react'
import { Package, Trash2 } from 'lucide-react'
import { Button } from './Button'
import { ConfirmDialog } from './ConfirmDialog'
import { useAccessPackage } from '@/lib/accessPackage'

/**
 * Floating access package action shared by Role Lookup and Release Roles. It only describes and clears the package; the temporary
 * role selection (comparison) has its own bar with its own Clear selection, so neither action can claim to operate on the other.
 */
export function AccessPackageBar({ onOpen }: { onOpen: () => void }) {
  const cart = useAccessPackage(), [confirmClear, setConfirmClear] = useState(false), count = cart.items.length
  if (!count) return null
  return (
    <div className="floating-bar" role="region" aria-label="Access package selection">
      <div>
        <p className="text-base font-black leading-none" style={{ color:'var(--text)' }}>
          <span style={{ color:'var(--accent2)' }}>{count}</span>{' '}
          {count === 1 ? 'role' : 'roles'} in access package
        </p>
        <p className="text-[10px] mt-0.5" style={{ color:'var(--muted)' }}>proposed names only</p>
      </div>
      <Button variant="primary" onClick={onOpen} aria-haspopup="dialog">
        <Package size={16} aria-hidden="true" />Access package ({count})
      </Button>
      <Button variant="secondary" onClick={() => setConfirmClear(true)}><Trash2 size={16} aria-hidden="true" />Clear package</Button>
      {confirmClear && (
        <ConfirmDialog title="Clear the access package?" confirmLabel="Clear package" onCancel={() => setConfirmClear(false)} onConfirm={() => { cart.clear(); setConfirmClear(false) }}>
          <p>This removes all {count} {count === 1 ? 'role' : 'roles'}, the default suffix and every role-specific suffix from the package. Selected roles, SAP roles and the imported data are not changed.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
