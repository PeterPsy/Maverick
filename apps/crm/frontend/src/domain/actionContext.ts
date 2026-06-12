import { CrmRecord, RecordsTablePayload } from '../api';
import { ActionDialogState, ComposerState, ImportPreview, RecordEntityFilter, ViewId } from './types';

export type EntitySelection = { entity: string; record: CrmRecord } | null;

export type CrmActionContext = {
  actionDialog: ActionDialogState;
  bulkSelection: Set<string>;
  filters: Record<string, string>;
  recordsCursor: string;
  recordsData: RecordsTablePayload | null;
  recordsCursorHistory: string[];
  recordEntityFilter: RecordEntityFilter;
  selected: EntitySelection;
  setActionDialog: (value: ActionDialogState) => void;
  setBulkSelection: (value: Set<string>) => void;
  setComposer: (value: ComposerState) => void;
  setError: (value: string) => void;
  setFilters: (value: Record<string, string>) => void;
  setImportPreview: (value: ImportPreview | null) => void;
  setIsSaving: (value: boolean) => void;
  setRecordEntityFilter: (value: RecordEntityFilter) => void;
  setRecordsCursor: (value: string) => void;
  setRecordsCursorHistory: (value: (history: string[]) => string[]) => void;
  setSelected: (value: EntitySelection) => void;
  setView: (value: ViewId) => void;
  view: ViewId;
  query: string;
  refresh: () => Promise<void>;
  refreshPipelineBoard: () => Promise<void>;
  refreshRecords: (cursor?: string) => Promise<void>;
};
