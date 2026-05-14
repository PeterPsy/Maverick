import type { DynamicViewsListOptions } from '../api';
import type { DynamicViewInstance } from '../types';

export type ViewReference = {
  entity_id?: string;
  entity_type?: string;
};

export type ViewFilter = {
  mode?: 'custom' | 'search' | string;
  query?: string;
  refs?: ViewReference[];
  status?: string;
  title?: string;
};

export const DEFAULT_VIEW_FILTER: ViewFilter = {
  mode: 'search',
  query: '',
  refs: [],
  status: 'all'
};

function normalizedSearchText(value: string) {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

function searchTokens(value: string) {
  return normalizedSearchText(value).split(/[^a-z0-9]+/).filter(Boolean);
}

function tokenMatches(haystack: string, token: string) {
  if (haystack.includes(token)) {
    return true;
  }
  return token.length > 3 && token.endsWith('s') && haystack.includes(token.slice(0, -1));
}

export function viewMatchesSearch(view: DynamicViewInstance, query: string) {
  if (!query) return true;
  const bindings = view.data_bindings || [];
  const searchableValues = [
    view.title,
    view.summary,
    view.id,
    view.status,
    view.snapshot_mode,
    view.package.title,
    view.package.summary,
    view.package.renderer,
    ...(view.package.tags || []),
    ...bindings.flatMap((binding) => [binding.source_type, binding.source_ref, binding.query || ''])
  ];
  const haystack = normalizedSearchText(searchableValues.join(' '));
  const normalizedQuery = normalizedSearchText(query);
  if (haystack.includes(normalizedQuery)) {
    return true;
  }
  const tokens = searchTokens(query);
  return tokens.length > 0 && tokens.every((token) => tokenMatches(haystack, token));
}

export function selectedViewIdsFromFilter(filter?: ViewFilter | null) {
  if (filter?.mode !== 'custom') {
    return [];
  }
  const refs = Array.isArray(filter.refs) ? filter.refs : [];
  const ids: string[] = [];
  refs.forEach((ref) => {
    const id = String(ref.entity_id || '').trim();
    if (ref.entity_type === 'view' && id && !ids.includes(id)) {
      ids.push(id);
    }
  });
  return ids;
}

export function listOptionsFromFilter(filter?: ViewFilter | null): DynamicViewsListOptions {
  const selectedIds = selectedViewIdsFromFilter(filter);
  const status = filter?.status === 'ready' ? 'ready' : undefined;
  const query = String(filter?.query || '').trim();
  if (selectedIds.length) {
    return {
      ...(status ? { status } : {}),
      ...(query ? { query } : {}),
      limit: selectedIds.length,
      view_ids: selectedIds
    };
  }
  return {
    ...(status ? { status } : {}),
    ...(query ? { query } : {}),
    limit: 500
  };
}
