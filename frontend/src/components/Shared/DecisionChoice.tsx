import { Check, Search, Trash2 } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { Button, type ButtonProps } from './Button'

/** The three proposed assignment decisions, always presented in this order. Values are the API values and never change. */
export const DECISION_ORDER = ['Investigate', 'Keep', 'Remove'] as const
export type DecisionChoiceValue = (typeof DECISION_ORDER)[number]

/** Neutral until selected. Selected: Investigate uses the configurable primary theme color, Keep the success tokens, Remove the danger tokens. */
export function decisionVariant(value: DecisionChoiceValue, selected: boolean): NonNullable<ButtonProps['variant']> {
  if (!selected) return 'secondary'
  return value === 'Investigate' ? 'primary' : value === 'Keep' ? 'success' : 'destructive'
}

export const DECISION_ICON: Record<DecisionChoiceValue, (size: number) => ReactNode> = {
  Investigate: (size) => <Search size={size} aria-hidden="true" />,
  Keep: (size) => <Check size={size} aria-hidden="true" />,
  Remove: (size) => <Trash2 size={size} aria-hidden="true" />,
}

/** Labelled toggle group for one proposed decision (selection is optional: nothing is preselected). */
export function DecisionChoice({ label, value, onChange, disabled, emptyHint }: { label: string; value: DecisionChoiceValue | null; onChange: (value: DecisionChoiceValue) => void; disabled?: boolean; emptyHint?: string }) {
  const hint = useId()
  return (
    <>
    <div role="group" aria-label={label} aria-describedby={emptyHint && value === null ? hint : undefined} className="decision-choice flex flex-wrap gap-1">
      {DECISION_ORDER.map((option) => (
        <Button key={option} size="compact" aria-pressed={value === option} variant={decisionVariant(option, value === option)} disabled={disabled} onClick={() => onChange(option)}>
          {DECISION_ICON[option](14)}
          {option}
        </Button>
      ))}
    </div>
    {emptyHint && value === null && <p id={hint} className="ui-description">{emptyHint}</p>}
    </>
  )
}
