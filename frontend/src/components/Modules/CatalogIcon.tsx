import { lazy, Suspense, type ComponentType } from 'react'
import { Hash, type LucideProps } from 'lucide-react'
type IconProps = Omit<LucideProps, 'ref'>
const Glyph = lazy(() =>
  import('./IconCatalog')
    .then((module) => ({ default: module.CatalogGlyph }))
    .catch(() => ({
      default: ({ name: _name, ...props }: IconProps & { name: string }) => (
        <Hash {...props} />
      )
    }))
)
const components = new Map<string, ComponentType<IconProps>>()
export const iconLabel = (name: string) =>
  name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1 $2')
export function catalogIcon(name: string): ComponentType<IconProps> {
  if (!components.has(name))
    components.set(name, (props) => (
      <Suspense fallback={<Hash {...props} />}>
        <Glyph name={name} {...props} />
      </Suspense>
    ))
  return components.get(name)!
}
