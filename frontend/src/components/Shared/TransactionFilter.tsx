import { useEffect, useMemo, useRef, useState } from 'react'
import { ButtonGroup } from './Button'
import { FilterChip } from './FilterChip'
import { SearchInput } from './Controls'
import { ClearFilterButton } from './ClearFilterButton'

const normalize = (value: string) => value.trim().toUpperCase()
export function useTransactionFilter(resetKey?: string | null) {
  const [chips, setChips] = useState<string[]>([]),
    [input, setInput] = useState('')
  const codes = [...new Set([...chips, normalize(input)].filter(Boolean))]
  const key = JSON.stringify(codes)
  const [deferredKey, setDeferredKey] = useState(key)
  useEffect(() => {
    const timer = setTimeout(() => setDeferredKey(key), 180)
    return () => clearTimeout(timer)
  }, [key])
  useEffect(() => {
    setChips([])
    setInput('')
    setDeferredKey('[]')
  }, [resetKey])
  const deferredCodes = useMemo(
    () => JSON.parse(deferredKey) as string[],
    [deferredKey],
  )
  return {
    chips,
    input,
    setInput,
    setChips,
    codes,
    key,
    deferredKey,
    deferredCodes,
    settling: key !== deferredKey,
    clear: () => {
      setChips([])
      setInput('')
    },
  }
}
type Mode = 'and' | 'or' | 'any' | 'all'
const INCLUDE_OPTIONS = [{ value: 'and', label: 'ALL' }, { value: 'or', label: 'ANY' }]
const EXCLUDE_OPTIONS = [{ value: 'any', label: 'ANY' }, { value: 'all', label: 'ALL' }]

export function TransactionFilter<M extends Mode = 'and' | 'or'>({
  label,
  filter,
  placeholder = 'e.g. MIGO, ME23N, VA03',
  mode,
  onModeChange,
  modeOptions = INCLUDE_OPTIONS,
  help,
  showClear = true,
  compact = false,
  chipPrefix = '',
}: {
  label: string
  filter: ReturnType<typeof useTransactionFilter>
  placeholder?: string
  /** `and`/`or` (ALL/ANY) for the include group, `any`/`all` for the exclude group. */
  mode?: M
  onModeChange?: (value: M) => void
  modeOptions?: { value: string; label: string }[]
  /** One explicit sentence about what the current ANY/ALL choice does. */
  help?: string
  chipPrefix?: string
  compact?: boolean
  showClear?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState('')
  return (
    <div
      className="transaction-filter"
      role="group"
      aria-label={label}
      aria-busy={filter.settling}
    >
      <label className="transaction-input-label text-sm">
        <span className={compact ? "sr-only" : undefined}>{label}</span>
          <SearchInput
            type="text"
            ref={input}
            aria-label={label}
            value={filter.input}
            placeholder={placeholder}
            maxLength={128}
            autoComplete="off"
            onChange={(event) => {
              filter.setInput(event.target.value)
              setMessage('')
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                const code = normalize(filter.input)
                if (code && !filter.chips.includes(code)) {
                  if (filter.chips.length >= 20) {
                    setMessage(
                      'At most 20 saved transaction filters; remove one before saving another.',
                    )
                    return
                  }
                  filter.setChips([...filter.chips, code])
                }
                filter.setInput('')
                input.current?.focus()
              } else if (
                event.key === 'Backspace' &&
                !filter.input &&
                filter.chips.length
              ) {
                event.preventDefault()
                filter.setChips(filter.chips.slice(0, -1))
              }
            }}
          />
      </label>
      {showClear && filter.codes.length > 0 && (
        <ClearFilterButton
          onClick={() => {
            filter.clear()
            setMessage('')
            input.current?.focus()
          }}
        />
      )}
      {(filter.chips.length > 0 || (mode && filter.codes.length > 1)) && (
        <div className="transaction-chips" aria-label="Transaction filters">
          {mode && onModeChange && filter.codes.length > 1 && (
            <ButtonGroup label={`${label} matching`} value={mode} options={modeOptions} onChange={value=>onModeChange(value as M)}/>
          )}
          {filter.chips.map((code) => (
            <FilterChip key={code} removeLabel={`Remove transaction ${code}`} onRemove={()=>{filter.setChips(filter.chips.filter(item=>item!==code));input.current?.focus()}}>{chipPrefix}{code}</FilterChip>
          ))}
        </div>
      )}
      {help && filter.codes.length > 0 && <p className="transaction-help text-xs text-[var(--muted)]">{help}</p>}
      {message && <p role="status">{message}</p>}
    </div>
  )
}

export interface TransactionGroupsState {
  include: ReturnType<typeof useTransactionFilter>
  includeMode: 'and' | 'or'
  setIncludeMode: (value: 'and' | 'or') => void
  exclude: ReturnType<typeof useTransactionFilter>
  excludeMode: 'any' | 'all'
  setExcludeMode: (value: 'any' | 'all') => void
}
const noun = (subject: 'roles' | 'users') => (subject === 'roles' ? 'roles' : 'users')
/** Explicit wording for the include group (find holders of the transactions). */
export const includeHelp = (subject: 'roles' | 'users', mode: 'and' | 'or') =>
  `${mode === 'or' ? 'ANY' : 'ALL'}: ${noun(subject)} holding ${mode === 'or' ? 'at least one of' : 'every one of'} these transactions.`
/** Explicit wording for the exclude group, including the rule that missing evidence is never proof of absence. */
export const excludeHelp = (subject: 'roles' | 'users', mode: 'any' | 'all') =>
  `${mode === 'any' ? 'ANY' : 'ALL'}: leave out ${noun(subject)} holding ${mode === 'any' ? 'at least one of' : 'every one of'} these transactions. ${subject === 'roles' ? 'Roles without mapped transactions are not listed.' : 'Users with unmapped roles are not listed.'}`

/** Independent include and exclude transaction groups; an empty group is inactive and a record must satisfy include and not the exclusion. */
export function TransactionFilterGroups({ subject, groups, includeLabel, excludeLabel }: { subject: 'roles' | 'users'; groups: TransactionGroupsState; includeLabel: string; excludeLabel: string }) {
  return (
    <div className="grid min-w-0 gap-3">
      <TransactionFilter label={includeLabel} filter={groups.include} mode={groups.includeMode} onModeChange={groups.setIncludeMode} help={includeHelp(subject, groups.includeMode)} showClear={false} />
      <TransactionFilter label={excludeLabel} filter={groups.exclude} mode={groups.excludeMode} onModeChange={groups.setExcludeMode} modeOptions={EXCLUDE_OPTIONS} help={excludeHelp(subject, groups.excludeMode)} showClear={false} placeholder="e.g. SU01, SE16" />
    </div>
  )
}
