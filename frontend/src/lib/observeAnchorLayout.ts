/** Keep portalled controls attached when async content moves an unchanged anchor.
 * No timers or frame polling: observe real content/ancestor layout changes while open.
 */
export function observeAnchorLayout(anchor:HTMLElement,panel:HTMLElement|null,place:()=>void) {
 const ancestors:HTMLElement[]=[]
 for(let node:HTMLElement|null=anchor;node;node=node.parentElement)ancestors.push(node)
 const sizes=new ResizeObserver(place)
 for(const node of ancestors)sizes.observe(node)
 if(panel)sizes.observe(panel)
 const content=new MutationObserver(place)
 content.observe(anchor.closest('main,[role="dialog"]')||anchor.parentElement||anchor,{childList:true,subtree:true,characterData:true})
 const styles=new MutationObserver(place)
 for(const node of ancestors)styles.observe(node,{attributes:true,attributeFilter:['style','class','hidden','open']})
 window.addEventListener('resize',place)
 window.addEventListener('scroll',place,true)
 return ()=>{sizes.disconnect();content.disconnect();styles.disconnect();window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true)}
}
