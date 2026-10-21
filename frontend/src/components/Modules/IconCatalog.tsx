import { lazy, Suspense, type ComponentType } from 'react'
import { Hash, type LucideProps } from 'lucide-react'
import dynamicIconImports from 'lucide-react/dynamicIconImports'

// Lucide owns this catalog. Only the requested SVG module is loaded, not every icon.
const loaders = Object.fromEntries(
  Object.entries(dynamicIconImports).map(([slug, load]) => [
    slug
      .split('-')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(''),
    load
  ])
)
export const iconNames = Object.keys(loaders).sort()
export const iconLabel = (name: string) =>
  name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1 $2')
type IconProps = Omit<LucideProps, 'ref'>
const components = new Map<string, ComponentType<IconProps>>()
export function catalogIcon(name: string): ComponentType<IconProps> {
  if (!Object.prototype.hasOwnProperty.call(loaders, name)) return Hash
  if (!components.has(name)) {
    const Icon = lazy(async () => {
      try {
        return await loaders[name]()
      } catch {
        return { default: Hash }
      }
    })
    components.set(name, (props) => (
      <Suspense fallback={<Hash {...props} />}>
        <Icon {...props} />
      </Suspense>
    ))
  }
  return components.get(name)!
}

export function CatalogGlyph({ name, ...props }: IconProps & { name: string }) {
  const Icon = catalogIcon(name)
  return <Icon {...props} />
}
