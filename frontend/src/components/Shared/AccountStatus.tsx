import { StatusBadge } from './Presentation'
import {
  CircleCheck,
  CircleX,
  CircleHelp,
  LockKeyhole,
  LockOpen,
  Check,
  MinusCircle,
} from 'lucide-react'
export function accountValidity(value: string) {
  const states = value.split('/')
  return states.every((s) => s === 'active' || s === 'Valid')
    ? 'Valid'
    : states.length > 0 &&
        states.every((s) => ['expired', 'future', 'Invalid'].includes(s))
      ? 'Invalid'
      : 'Unknown'
}
export function AccountStatus({
  value,
  kind = 'validity',
}: {
  value: string
  kind?: 'validity' | 'lock' | 'ad'
}) {
  const text =
    kind === 'validity'
      ? accountValidity(value)
      : ['Locked', 'Unlocked', 'Enabled', 'Disabled'].includes(value)
        ? value
        : 'Unknown'
  const positive = ['Valid', 'Unlocked', 'Enabled'].includes(text),
    negative = ['Invalid', 'Locked', 'Disabled'].includes(text)
  const Icon =
    text === 'Locked'
      ? LockKeyhole
      : text === 'Unlocked'
        ? LockOpen
        : text === 'Enabled'
          ? Check
          : text === 'Disabled'
            ? MinusCircle
            : positive
              ? CircleCheck
              : negative
                ? CircleX
                : CircleHelp
  return (
    <StatusBadge tone={positive?'success':negative?'error':'neutral'}
      className={kind==='lock'?`lock-status ${text==='Locked'?'lock-status-locked':''}`:''}
    >
      <Icon size={13} aria-hidden="true" />
      {text}
    </StatusBadge>
  )
}
export const userTypeLabel = (value: string) =>
  (
    ({
      A: 'Dialog',
      B: 'System',
      C: 'Communication',
      S: 'Service',
      L: 'Reference',
    }) as Record<string, string>
  )[value.toUpperCase()]
    ? `${value} · ${({ A: 'Dialog', B: 'System', C: 'Communication', S: 'Service', L: 'Reference' } as Record<string, string>)[value.toUpperCase()]}`
    : value || 'Unknown'
