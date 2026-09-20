/** Visibility is the intersection of the document and the owning shell surface. */
export function widgetVisible(active: boolean, pageVisible: boolean, collapsed: boolean): boolean {
  return active && pageVisible && !collapsed;
}
