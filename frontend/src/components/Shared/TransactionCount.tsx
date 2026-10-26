import { Zap } from 'lucide-react'
export function TransactionCount({count}:{count:number}) {
 return <span className="transaction-count" title={`${count.toLocaleString()} mapped transactions`} aria-label={`${count} transactions`}><Zap size={12} aria-hidden="true"/>{count.toLocaleString()}</span>
}
