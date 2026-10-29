import { Package } from 'lucide-react'
import { Button } from './Button'
import { useAccessPackage } from '@/lib/accessPackage'

/** Floating access package action shared by Role Lookup and Release Roles; independent of comparison and of the package size. */
export function AccessPackageBar({ onOpen }: { onOpen: () => void }) {
  const cart = useAccessPackage()
  if (!cart.items.length) return null
  return (
    <div className="floating-bar" role="region" aria-label="Access package selection">
      <div>
        <p className="text-base font-black leading-none" style={{ color:'var(--text)' }}>
          <span style={{ color:'var(--accent2)' }}>{cart.items.length}</span>{' '}
          {cart.items.length === 1 ? 'role' : 'roles'} in access package
        </p>
        <p className="text-[10px] mt-0.5" style={{ color:'var(--muted)' }}>proposed names only</p>
      </div>
      <Button variant="primary" onClick={onOpen} aria-haspopup="dialog">
        <Package size={16} aria-hidden="true" />Access package ({cart.items.length})
      </Button>
    </div>
  )
}
