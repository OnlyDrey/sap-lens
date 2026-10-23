import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
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
export function TransactionFilter({
  label,
  filter,
  placeholder = 'e.g. MIGO',
  mode,
  onModeChange,
  showClear = true,
}: {
  label: string
  filter: ReturnType<typeof useTransactionFilter>
  placeholder?: string
  mode?: 'and' | 'or'
  onModeChange?: (value: 'and' | 'or') => void
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
        {label}
        <span className="transaction-input">
          <Search size={15} aria-hidden="true" />
          <input
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
        </span>
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
            <div
              className="segmented-control"
              role="group"
              aria-label="Transaction matching"
            >
              {(['and', 'or'] as const).map((operator) => (
                <button
                  key={operator}
                  type="button"
                  aria-pressed={mode === operator}
                  onClick={() => onModeChange(operator)}
                >
                  {operator.toUpperCase()}
                </button>
              ))}
            </div>
          )}
          {filter.chips.map((code) => (
            <span className="transaction-chip" key={code}>
              {code}
              <button
                type="button"
                aria-label={`Remove transaction ${code}`}
                onClick={() => {
                  filter.setChips(filter.chips.filter((item) => item !== code))
                  input.current?.focus()
                }}
              >
                <X size={13} aria-hidden="true" />
              </button>
            </span>
          ))}
          <span className="text-xs text-[var(--muted)]">
            {mode === 'and' ? 'Match all (AND)' : 'Match any (OR)'}
          </span>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  )
}
