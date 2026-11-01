/** True when Escape was pressed on a control whose own list is open (a select, a combobox or a popover trigger): that control closes first, a surrounding dialog or panel stays. */
export const openListOwnsEscape = (event: KeyboardEvent) => {
  const target = event.target
  return target instanceof Element && target.matches('[aria-expanded="true"][role="combobox"], select[aria-expanded="true"], [aria-expanded="true"][aria-haspopup]')
}
