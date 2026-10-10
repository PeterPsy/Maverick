import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import SlidingPagination from './components/ui/sliding-pagination';

type Props = {
  query: string;
  onQueryChange: (query: string) => void;
  loading: boolean;
  refreshing: boolean;
  refreshDisabled: boolean;
  onRefresh: () => void;
  start: number;
  end: number;
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
};

export function MailToolbar(props: Props) {
  return (
    <header className="toolbar">
      <label className="mail-search">
        <span className="mail-search__icon" aria-hidden="true" />
        <input aria-label="Search in Mail" value={props.query}
          onChange={(event) => props.onQueryChange(event.target.value)} placeholder="Search in Mail" />
      </label>
      <div className="mail-page-controls" aria-label="Mail navigation">
        <span className={`mail-page-range ${props.loading ? 'is-loading' : ''}`} aria-live="polite">
          {props.loading ? <span aria-hidden="true" /> : `${props.start}-${props.end}`}
        </span>
        {props.totalPages > 1 ? <>
          <SlidingPagination className="mail-pagination-full" totalPages={props.totalPages}
            currentPage={props.page} onPageChange={props.onPageChange} maxVisiblePages={7} />
          <nav className="mail-pagination-compact" aria-label="Mail pages">
            <button type="button" className="mail-icon-button" aria-label="Previous mail page"
              disabled={props.page <= 1} onClick={() => props.onPageChange(props.page - 1)}><ChevronLeft size={16} /></button>
            <span>{props.page} / {props.totalPages}</span>
            <button type="button" className="mail-icon-button" aria-label="Next mail page"
              disabled={props.page >= props.totalPages} onClick={() => props.onPageChange(props.page + 1)}><ChevronRight size={16} /></button>
          </nav>
        </> : null}
        <button type="button" className="mail-icon-button" onClick={props.onRefresh}
          disabled={props.refreshDisabled} aria-label="Load more mail" title="Load more mail" aria-busy={props.refreshing}>
          <RefreshCw className={props.refreshing ? 'is-spinning' : undefined} size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
