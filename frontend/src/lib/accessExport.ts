import { accessQuery, type UserDetail, type Assignment } from '@/api/access'
import { applicationToken } from '@/api/client'

// Quote every field; neutralise spreadsheet formulas without changing normal SAP identifiers.
export function csvField(value: unknown): string {
  let text = value == null ? '' : String(value)
  if (/^[\s\u0000-\u001f]*[=+@\-]/u.test(text) || /^[\t\r\n]/u.test(text)) text = "'" + text
  return '"' + text.replace(/"/g, '""') + '"'
}
const csvHeader = ['Username', 'User group', 'Full name', 'Role', 'Role description', 'Role family', 'Valid from', 'Valid to', 'Assignment status', 'Document type', 'Release group', 'Release strategy'].map(csvField).join(',')
function assignmentLine(user: UserDetail, a: Assignment): string {
  return [user.username, a.user_group, [user.first_name, user.last_name].filter(Boolean).join(' '), a.role_name, a.role_description, a.scope === 'business' ? 'Business' : 'Release', a.valid_from, a.valid_to, a.status, a.release?.document_type, a.release?.release_group, a.release?.release_strategy].map(csvField).join(',') + '\r\n'
}
export async function exportAssignments(user: UserDetail, scope: string, status: string, current: () => boolean, tcodes: string[] = [], dates: Record<string, string> = {}, transactionMode: 'and' | 'or' = 'and'): Promise<boolean> {
  const chunks = ['\ufeff' + csvHeader + '\r\n'], seen = new Set<number>()
  const encoder = new TextEncoder()
  let byteCount = encoder.encode(chunks[0]).byteLength
  for (let offset = 0; offset < user.total; offset += 100) {
    if (!current()) throw new Error('Export cancelled because the selected user or filters changed.')
    const page = await accessQuery<UserDetail>(`users/${encodeURIComponent(user.username)}`, { scope, tcodes, transaction_mode: transactionMode, ...dates, status: status === 'all' ? '' : status, show_expired: status === 'all', offset, limit: 100 })
    if (page.data_revision !== user.data_revision || page.total !== user.total || page.as_of !== user.as_of) throw new Error('Source data changed. Refresh the user before exporting.')
    if (!page.items.length) throw new Error('Incomplete assignment response. Refresh and retry.')
    for (const row of page.items) {
      if (seen.has(row.id) || !['business', 'release'].includes(row.scope)) throw new Error('Inconsistent assignment response. Refresh and retry.')
      const line = assignmentLine(user, row)
      byteCount += encoder.encode(line).byteLength
      if (byteCount > 32 * 1024 * 1024) throw new Error('Export exceeds the 32 MiB safety limit. Narrow the assignment filters.')
      seen.add(row.id); chunks.push(line)
    }
  }
  if (seen.size !== user.total || !current()) throw new Error('Export cancelled or incomplete.')
  const content = chunks.join('')
  const filename = `sap-lens-${user.username.replace(/[^a-z0-9_-]/gi, '_').slice(0, 80)}-${scope}-${user.as_of}.csv`
  if (window.pywebview) {
    if (!window.pywebview.api.save_user_access_csv) throw new Error('This desktop version does not support CSV export. Update the desktop application.')
    return window.pywebview.api.save_user_access_csv(applicationToken(), filename, content)
  }
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = filename
  document.body.append(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}
