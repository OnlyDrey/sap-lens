/** Non-overlapping ranges of distinct currently valid roles per SAP user. Mirrors `ASSIGNMENT_BANDS` in backend/user_access.py. */
export const ASSIGNMENT_BANDS = ['0–5', '6–10', '11–20', '21–30', '31+'] as const
/** Earlier saved filters and links used other ranges; they stay valid but are not offered. */
export const LEGACY_ASSIGNMENT_BANDS = ['0', '1–5', '6–20', '21+'] as const
