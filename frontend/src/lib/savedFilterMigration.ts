/**
 * Saved Role Lookup and User Access filters from before the independent include/exclude groups store one transaction list with
 * an exclude switch. The same condition is restored exactly: AND-exclude ("not all together") becomes Exclude ALL and
 * OR-exclude ("none of them") becomes Exclude ANY. Entries without the old fields are returned unchanged.
 */
export function migrateTransactionFilters(filters: Record<string, unknown>): Record<string, unknown> {
  if (Array.isArray(filters.excludeTcodes)) return filters
  const list = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [])
  const { transactionExclude, transactionOperator, notTcodes, ...rest } = filters
  const mode = rest.transactionMode === 'or' ? 'or' : 'and'
  if (list(notTcodes).length && !list(rest.tcodes).length) {
    return { ...rest, tcodes: [], transactionMode: 'and', excludeTcodes: list(notTcodes), excludeMode: 'any' }
  }
  if (transactionExclude === true || (transactionOperator === 'not' && transactionExclude !== true && list(rest.tcodes).length)) {
    const legacyOr = transactionExclude === true ? mode === 'or' : true
    return { ...rest, tcodes: [], transactionMode: 'and', excludeTcodes: list(rest.tcodes), excludeMode: legacyOr ? 'any' : 'all' }
  }
  return { ...rest, ...(('tcodes' in rest || 'transactionMode' in rest) ? { excludeTcodes: [], excludeMode: 'any' } : {}) }
}
