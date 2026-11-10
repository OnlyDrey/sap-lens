import {test} from 'node:test'
import assert from 'node:assert/strict'
import {hasPriorReview,isEligibleAssignment} from '../../src/lib/sodBulkSelection.ts'
import type {AssignmentPick} from '../../src/api/sod.ts'
const row=(decision:AssignmentPick['decision'],has_review=decision!=='Pending')=>({key:decision,user:'SYN_USER',ref:'SYN_ROLE',suffix:'',evidence_version:'synthetic',user_group:'FIN',decision,has_review})
test('eligibility distinguishes matching assignments, prior reviews and unchanged decisions',()=>{
 const rows=[row('Pending'),row('Keep'),row('Removal required'),row('Investigate'),row('Outdated')]
 assert.equal(rows.filter(r=>isEligibleAssignment(r,'Keep',false)).length,1)
 assert.equal(rows.filter(r=>isEligibleAssignment(r,'Keep',true)).length,4)
 assert.equal(rows.filter(r=>isEligibleAssignment(r,'Remove',true)).length,4)
 assert.equal(rows.filter(r=>isEligibleAssignment(r,'Investigate',true)).length,4)
 assert.equal(rows.filter(r=>isEligibleAssignment(r,'Keep',true,false)).length,0)
 assert.equal(hasPriorReview(row('Outdated')),true)
})

import {bulkSelectionScope,selectAssignmentPage} from '../../src/lib/sodBulkSelection.ts'
test('page selection preserves other pages and filter-outside selections without executing them',()=>{
 const first={...row('Pending'),key:'first'},second={...row('Pending'),key:'second'},outside={...row('Pending'),key:'outside'}
 const initial=new Map([[outside.key,outside]])
 const chosen=selectAssignmentPage(initial,[first,second],true)
 assert.equal(chosen.size,3)
 assert.deepEqual(bulkSelectionScope([first,second],chosen,'Keep',false).executable.map(r=>r.key),['first','second'])
 assert.deepEqual(bulkSelectionScope([first],chosen,'Keep',false).outside.map(r=>r.key),['outside','second'])
 const cleared=selectAssignmentPage(chosen,[first],false)
 assert.deepEqual([...cleared.keys()],['outside','second'])
})
test('previously reviewed and unchanged selections cannot enter an executable operation',()=>{
 const pending=row('Pending'),kept=row('Keep'),selected=new Map([[pending.key,pending],[kept.key,kept]])
 assert.equal(bulkSelectionScope([pending,kept],selected,'Remove',false).executable.length,1)
 assert.equal(bulkSelectionScope([pending,kept],selected,'Keep',true).executable.length,1)
 assert.equal(bulkSelectionScope([pending,kept],selected,'Remove',true).executable.length,2)
})

import {sortBulkRows} from '../../src/lib/sodBulkSelection.ts'
test('assignment order is deterministic before pagination, including repeated role intervals',()=>{
 const rows=[{...row('Pending'),key:'3',user:'SYN_B'},{...row('Pending'),key:'2'},{...row('Pending'),key:'1'}]
 assert.deepEqual(sortBulkRows(rows).map(r=>r.key),['3','1','2'])
 assert.deepEqual(rows.map(r=>r.key),['3','2','1'])
})
