import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MailToolbar } from '../../../../mail/frontend/src/MailToolbar';
import '../../../../mail/frontend/src/styles.css';

function ToolbarFixture() {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [refreshes, setRefreshes] = useState(0);
  return <>
    <MailToolbar query={query} onQueryChange={setQuery} loading={false} refreshing={false} refreshDisabled={false}
      onRefresh={() => setRefreshes((count) => count + 1)} start={1} end={50} page={page} totalPages={20} onPageChange={setPage} />
    <button type="button" data-testid="outside">Email row</button>
    <output data-testid="refreshes">{refreshes}</output>
    <output data-testid="query">{query}</output>
  </>;
}
createRoot(document.getElementById('root')!).render(<ToolbarFixture />);
