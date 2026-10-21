import type { ComponentType, CSSProperties } from 'react'
import type { LucideProps } from 'lucide-react'
import { contrast, isHex } from '@/lib/theme'
import { useModulePalette, useModuleVisual } from './ModuleRegistry'

export function ModuleIcon({
  moduleId,
  Icon: customIcon,
  color: customColor,
  size = 'small',
  selected = false,
  disabled = false
}: {
  moduleId?: string | null
  Icon?: ComponentType<LucideProps>
  color?: string | null
  size?: 'small' | 'medium' | 'large'
  selected?: boolean
  disabled?: boolean
}) {
  const visual = useModuleVisual(moduleId)
  const palette = useModulePalette()
  const color = isHex(customColor || visual.color)
    ? customColor || visual.color
    : '#64748b'
  const background =
    '#' +
    [1, 3, 5]
      .map((i) =>
        Math.round(
          parseInt(color.slice(i, i + 2), 16) * 0.1 +
            parseInt(palette.surface.slice(i, i + 2), 16) * 0.9
        )
          .toString(16)
          .padStart(2, '0')
      )
      .join('')
  const foreground =
    contrast(color, background) >= 3
      ? color
      : contrast(palette.text, background) >= 4.5
        ? palette.text
        : contrast('#ffffff', background) >= 4.5
          ? '#ffffff'
          : '#000000'
  const Icon = customIcon || visual.Icon
  return (
    <span
      aria-hidden="true"
      data-module-icon
      data-selected={selected}
      data-disabled={disabled}
      className={`module-icon module-icon-${size}`}
      style={
        {
          '--module-tint': background,
          '--module-foreground': foreground
        } as CSSProperties
      }
    >
      <Icon size={size === 'large' ? 22 : size === 'medium' ? 18 : 14} />
    </span>
  )
}
