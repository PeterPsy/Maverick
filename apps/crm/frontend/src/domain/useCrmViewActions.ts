import { SavedView, callBackend } from '../api';
import { CrmActionContext } from './actionContext';

export function useCrmViewActions({
  filters,
  query,
  recordsCursor,
  recordsCursorHistory,
  recordsData,
  recordEntityFilter,
  refresh,
  setActionDialog,
  setError,
  setFilters,
  setIsSaving,
  setRecordsCursor,
  setRecordsCursorHistory,
  view
}: CrmActionContext) {
  async function clearCustomView() {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.clear_custom_view' });
      await refresh();
    } catch (clearError) {
      setError(clearError instanceof Error ? clearError.message : 'Unable to clear custom view.');
    } finally {
      setIsSaving(false);
    }
  }

  function saveCurrentView() {
    setActionDialog({ kind: 'save-view' });
  }

  async function submitSavedView(title: string): Promise<boolean> {
    if (!title.trim()) return false;
    setIsSaving(true);
    setError('');
    try {
      const entityType = view === 'records' ? recordEntityFilter : 'all';
      await callBackend({ action: 'crm.save_view', title: title.trim(), entity_type: entityType, query, filters });
      await refresh();
      return true;
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save view.');
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function applySavedView(savedView: SavedView) {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.apply_saved_view', id: savedView.id });
      setFilters(Object.fromEntries(Object.entries(savedView.filters || {}).map(([key, value]) => [key, String(value)])));
      await refresh();
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : 'Unable to apply saved view.');
    } finally {
      setIsSaving(false);
    }
  }

  function goToNextRecordsPage() {
    if (!recordsData?.next_cursor) return;
    setRecordsCursorHistory((history) => [...history, recordsCursor]);
    setRecordsCursor(recordsData.next_cursor);
  }

  function goToPreviousRecordsPage() {
    setRecordsCursorHistory((history) => {
      const nextHistory = [...history];
      const previous = nextHistory.pop() || '';
      setRecordsCursor(previous);
      return nextHistory;
    });
  }

  function goToRecordsPage(pageNumber: number) {
    const currentPage = recordsCursorHistory.length + 1;
    const targetPage = Math.max(1, Math.floor(pageNumber));
    if (targetPage === currentPage) return;
    if (targetPage === currentPage + 1 && recordsData?.next_cursor) {
      goToNextRecordsPage();
      return;
    }
    if (targetPage > currentPage) return;
    const nextCursor = targetPage === 1 ? '' : recordsCursorHistory[targetPage - 1] || '';
    setRecordsCursorHistory(() => recordsCursorHistory.slice(0, targetPage - 1));
    setRecordsCursor(nextCursor);
  }

  return {
    applySavedView,
    clearCustomView,
    goToRecordsPage,
    goToNextRecordsPage,
    goToPreviousRecordsPage,
    saveCurrentView,
    submitSavedView
  };
}
