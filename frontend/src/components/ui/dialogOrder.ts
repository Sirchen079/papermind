// Dialogs in this app render nested or through portals in opening order.
// A reader underneath a later drawer must leave its keyboard actions to that drawer.
export function isTopDialog(element:HTMLElement|null):boolean {
  const dialogs=Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"], [role="alertdialog"]')).filter(node=>node.getClientRects().length>0);
  return element!==null&&dialogs[dialogs.length-1]===element;
}
