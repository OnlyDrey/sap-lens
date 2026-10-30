/** Central health thresholds for share-based indicators (percent). Reused by every progress indicator that classifies a match quality. */
export const MATCH_HEALTH = { good: 95, fair: 85 } as const
export type HealthTone = 'success' | 'warning' | 'error'

/** Green from `good`, amber from `fair`, red below. Describes the measured share only, never the health of other data or SAP authorization. */
export const matchHealthTone = (percent: number): HealthTone => (percent >= MATCH_HEALTH.good ? 'success' : percent >= MATCH_HEALTH.fair ? 'warning' : 'error')
export const MATCH_HEALTH_LEGEND = `Green from ${MATCH_HEALTH.good}%, amber from ${MATCH_HEALTH.fair}%, red below ${MATCH_HEALTH.fair}%.`
