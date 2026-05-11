export type SidebarSelectionPage = {
  id: string;
};

export type SidebarSelectionSection = {
  id: string;
  pages: SidebarSelectionPage[];
};

export function sectionIdForPageId(sections: SidebarSelectionSection[], pageId: string): string {
  const normalizedPageId = pageId.trim();
  if (!normalizedPageId) {
    return '';
  }
  for (const section of sections) {
    if (section.pages.some((page) => page.id === normalizedPageId)) {
      return section.id;
    }
  }
  return '';
}

export function collapsedSectionsWithPageVisible(
  collapsedSections: ReadonlySet<string>,
  sections: SidebarSelectionSection[],
  pageId: string
): Set<string> {
  const next = new Set(collapsedSections);
  const sectionId = sectionIdForPageId(sections, pageId);
  if (sectionId) {
    next.delete(sectionId);
  }
  return next;
}
