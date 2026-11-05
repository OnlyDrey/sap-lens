import type {AssignmentPick,BulkAction} from '../api/sod'

export function hasPriorReview(row:AssignmentPick) {
 return row.has_review ?? (!!row.previous_decision || ['Keep','Removal required','Investigate','Outdated'].includes(row.decision))
}
export function isEligibleAssignment(row:AssignmentPick,action:BulkAction|null,includeReviewed:boolean,reviewable=true) {
 // Without a chosen decision nothing is "unchanged"; the operation still cannot be confirmed (see the dialog's ready condition).
 const unchanged=action===null?false:action==='Remove'?row.decision==='Removal required':row.decision===action
 return reviewable && (includeReviewed || !hasPriorReview(row)) && !unchanged
}

/** Retained out-of-filter selections are disclosed, but never executable. */
export function bulkSelectionScope(rows:readonly AssignmentPick[],selected:ReadonlyMap<string,AssignmentPick>,action:BulkAction|null,includeReviewed:boolean,reviewable=true) {
 const current=new Map(rows.map(row=>[row.key,row]))
 const matching=rows.filter(row=>isEligibleAssignment(row,action,includeReviewed,reviewable))
 const outside=[...selected.values()].filter(row=>!current.has(row.key))
 const executable=matching.filter(row=>selected.has(row.key))
 return {matching,outside,executable}
}
export function selectAssignmentPage(selected:ReadonlyMap<string,AssignmentPick>,rows:readonly AssignmentPick[],select:boolean) {
 const next=new Map(selected)
 for(const row of rows)if(select)next.set(row.key,row);else next.delete(row.key)
 return next
}

export function sortBulkRows(rows:readonly AssignmentPick[]) {
 return [...rows].sort((a,b)=>a.user.localeCompare(b.user,'en') || a.ref.localeCompare(b.ref,'en') || a.key.localeCompare(b.key,'en'))
}
