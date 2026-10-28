/**
 * Keyboard focus must never leave a control half hidden inside a horizontally scrolling strip or table.
 * Browsers only scroll a partly visible focus target when it is mostly hidden, so reveal it explicitly.
 */
export function installFocusReveal() {
  document.addEventListener('focusin', event => {
    const target = event.target
    if (!(target instanceof HTMLElement) || !target.matches(':focus-visible')) return
    for (let parent = target.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const overflowX = getComputedStyle(parent).overflowX
      if ((overflowX === 'auto' || overflowX === 'scroll') && parent.scrollWidth > parent.clientWidth) {
        const box = target.getBoundingClientRect(), area = parent.getBoundingClientRect()
        if (box.left < area.left || box.right > area.right) target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        return
      }
    }
  })
}
