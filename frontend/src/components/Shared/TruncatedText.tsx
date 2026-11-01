import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { Popover } from './Popover'

/**
 * One line of text that ends in an ellipsis when it does not fit. Only while it is actually cut off does it become a
 * button that reveals the complete text on hover, keyboard focus, click or tap (Escape closes it); a text that fits is
 * plain text with no extra tab stop and no redundant tooltip. The full text is always in the DOM for assistive technology.
 */
export function TruncatedText({ text, label = 'Full text' }: { text: string; label?: string }) {
  const host = useRef<HTMLSpanElement | null>(null)
  const [cut, setCut] = useState(false)
  const measure = useCallback(() => {
    const line = host.current?.querySelector<HTMLElement>('.truncated-text-line')
    if (line) setCut(line.scrollWidth - line.clientWidth > 1)
  }, [])
  useLayoutEffect(() => {
    measure()
    const element = host.current
    if (!element) return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    void document.fonts?.ready.then(measure)
    return () => observer.disconnect()
  }, [measure, text, cut])
  const line = <span className="truncated-text-line">{text}</span>
  return (
    <span ref={host} className="truncated-text" data-truncated={cut || undefined}>
      {cut ? (
        // data-np: a click here must not also activate a clickable card around the text.
        <span data-np className="truncated-text-slot">
          <Popover label={label} reveal="hover" isolateClicks triggerVariant="ghost" triggerClassName="truncated-trigger" className="truncated-popover" preferredWidth={420} trigger={line}>
            <p className="truncated-full">{text}</p>
          </Popover>
        </span>
      ) : line}
    </span>
  )
}
