/** Whether the open Settings view holds unsaved edits, so navigation elsewhere can ask before discarding them. */
let dirty = false
export const setSettingsDirty = (value: boolean) => { dirty = value }
export const settingsDirty = () => dirty
export const DISCARD_PROMPT = 'Discard unsaved settings changes?'
