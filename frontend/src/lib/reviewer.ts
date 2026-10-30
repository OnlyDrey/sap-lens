/** Self-reported reviewer name, remembered for the current browser session only. It is a convenience, not an authenticated identity. */
const key = 'sap-lens-sod-reviewer'
export const rememberedReviewer = () => { try { return sessionStorage.getItem(key) || '' } catch { return '' } }
export const rememberReviewer = (name: string) => { try { if (name.trim()) sessionStorage.setItem(key, name.trim()) } catch { /* optional convenience */ } }
