/** True when Escape was pressed on a control whose own list is open (a select, a combobox or a popover trigger): that control closes first, a surrounding dialog or panel stays. */
export const openListOwnsEscape = (event: KeyboardEvent) => {
  // Portal and parent listeners share document; whichever runs first must leave Escape to the inner popover.
  if(event.defaultPrevented||document.querySelector('.ui-popover[role="dialog"]'))return true
  const target = event.target
  return target instanceof Element && target.matches('[aria-expanded="true"][role="combobox"], select[aria-expanded="true"], [aria-expanded="true"][aria-haspopup]')
}
