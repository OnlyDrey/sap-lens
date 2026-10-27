/** Literal contains search, or anchored SAP '*' matching. No user regex execution. */
export function textMatches(value:string,query:string):boolean {
 const text=value.toLowerCase(),pattern=query.trim().toLowerCase()
 if(!pattern.includes('*'))return text.includes(pattern)
 const parts=pattern.split('*')
 if(!text.startsWith(parts[0]))return false
 let position=parts[0].length
 for(const part of parts.slice(1,-1)){
  const found=text.indexOf(part,position)
  if(found<0)return false
  position=found+part.length
 }
 const last=parts[parts.length-1]
 return text.endsWith(last)&&text.length-last.length>=position
}
