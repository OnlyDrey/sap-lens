/** Display-only source label; never changes canonical SAP classification or data. */
export function presentRoleDescription(description: string | null | undefined, knownAreas: readonly string[]) {
 const original = description?.trim() || ''
 const match = /^([A-Z][A-Z0-9-]*)\s+[-–—]\s+(.+)$/i.exec(original)
 const area = match?.[1].toUpperCase()
 return area && area!=='UNCLASSIFIED' && knownAreas.includes(area)
  ? {description: match![2].trim(), area}
  : {description: original, area: undefined}
}
