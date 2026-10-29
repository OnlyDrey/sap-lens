import { X } from 'lucide-react'
import { dismissExport, useExportNotice } from '@/lib/exportNotice'
import { IconButton } from './Button'

/** Fixed over the page top so announcing an export never moves the layout. */
export function ExportNotice() {
  const notice = useExportNotice()
  if (!notice) return null
  return (
    <div className="export-notice" data-kind={notice.kind} key={notice.id} role={notice.kind === 'error' ? 'alert' : 'status'}>
      <span className="export-notice-text">{notice.message}</span>
      {notice.kind === 'error' && <IconButton label="Dismiss export message" onClick={dismissExport}><X size={14} /></IconButton>}
    </div>
  )
}
