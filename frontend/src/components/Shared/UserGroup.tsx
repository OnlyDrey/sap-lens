/** The SAP User Group(s) of a record as plain text, joined for several groups. Empty when the data carries none. */
export const groupText = (groups?: string[] | string | null) => (Array.isArray(groups) ? groups.filter(Boolean).join(', ') : groups || '')

/**
 * One presentation of a SAP User Group for every table that has a dedicated "SAP User Group" column: compact single-line text (the complete value
 * stays in the tooltip when the column is narrow) and a muted dash with an accessible "No SAP User Group" for records that have none.
 */
export function UserGroupCell({ groups }: { groups?: string[] | string | null }) {
  const text = groupText(groups)
  return text
    ? <span className="user-group-text" title={`SAP User Group: ${text}`}>{text}</span>
    : <span className="user-group-text" data-missing="true" title="No SAP User Group in the imported data"><span aria-hidden="true">—</span><span className="sr-only">No SAP User Group</span></span>
}
