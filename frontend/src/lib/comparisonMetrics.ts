/** Symmetric set similarity; containment is directional and labelled separately. */
export function jaccard(shared:number,a:number,b:number) {
 const union=a+b-shared
 return union>0?Math.round(100*shared/union):0
}
export function containment(shared:number,total:number) {
 return total>0?Math.round(100*shared/total):0
}
