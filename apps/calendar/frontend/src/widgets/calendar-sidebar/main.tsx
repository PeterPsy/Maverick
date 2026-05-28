import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleUserRound, RefreshCw, Square, SquareCheck, TriangleAlert } from 'lucide-react';
import { listCalendars, listConnections, listEvents, selectCalendar, syncCalendar } from '../../api';
import {
  CALENDAR_UI_STATE_RESOURCE,
  readCalendarUiState,
  type CalendarUiState,
} from '../../calendar-ui-state';
import type { CalendarConnection, CalendarRemoteCalendar, Event } from '../../components/ui/calendar-types';
import { calendarAccountFilterValues } from '../../components/ui/calendar-utils';
import {
  TreeExpander,
  TreeIcon,
  TreeLabel,
  TreeNode,
  TreeNodeContent,
  TreeNodeTrigger,
  TreeProvider,
  TreeView,
} from '../../components/ui/tree';
import { runtimeAppIdFromPathname } from '../../runtime';
import './styles.css';

type AccountGroup = {
  id: string;
  name: string;
  provider: 'local' | string;
  status: string;
  connection?: CalendarConnection;
  calendars: CalendarRemoteCalendar[];
  eventCount: number;
};

type CalendarTreeNode = {
  account?: AccountGroup;
  calendar?: CalendarRemoteCalendar;
  children: CalendarTreeNode[];
  id: string;
  label: string;
  loading?: boolean;
  status?: string;
  title: string;
  type: 'account' | 'calendar';
};

function CalendarSidebarWidget() {
  const appId = runtimeAppIdFromPathname(window.location.pathname);
  const [events, setEvents] = useState<Event[]>([]);
  const [connections, setConnections] = useState<CalendarConnection[]>([]);
  const [calendars, setCalendars] = useState<CalendarRemoteCalendar[]>([]);
  const [uiState, setUiState] = useState<CalendarUiState>(() => readCalendarUiState(appId));
  const [isLoading, setIsLoading] = useState(true);
  const [activeOperation, setActiveOperation] = useState('');
  const [error, setError] = useState('');

  const accountGroups = useMemo(
    () => buildAccountGroups(events, connections, calendars),
    [events, connections, calendars],
  );
  const accountTreeNodes = useMemo(
    () => buildCalendarTree(accountGroups, activeOperation),
    [accountGroups, activeOperation],
  );
  const defaultExpandedIds = useMemo(
    () => accountTreeNodes.flatMap((node) => collectDefaultExpandedIds(node)),
    [accountTreeNodes],
  );
  const selectedNodeIds = useMemo(
    () => uiState.selectedAccounts.length > 0
      ? uiState.selectedAccounts.map((accountId) => calendarAccountIdentity(accountId))
      : [],
    [uiState.selectedAccounts],
  );
  const treeProviderKey = `${accountGroups.length}:${calendars.length}:${defaultExpandedIds.join('|')}`;

  async function refreshCalendarState() {
    setIsLoading(true);
    try {
      const [nextEvents, nextConnections, nextCalendars] = await Promise.all([listEvents(appId), listConnections(appId), listCalendars(appId)]);
      setEvents(nextEvents);
      setConnections(nextConnections);
      setCalendars(nextCalendars);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Calendar accounts.');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void refreshCalendarState();
  }, [appId]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.owner_app_id !== appId && payload.type !== 'maverick.widget.context-changed') {
        return;
      }
      if (payload.type === 'maverick.widget.context-changed') {
        setUiState(readCalendarUiState(appId));
        void refreshCalendarState();
        return;
      }
      if (payload.type === 'maverick.widget.data-changed') {
        if (payload.resource === CALENDAR_UI_STATE_RESOURCE) {
          setUiState(readCalendarUiState(appId));
          return;
        }
        void refreshCalendarState();
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  async function toggleRemoteCalendar(calendar: CalendarRemoteCalendar, checked: boolean) {
    setActiveOperation(calendar.id);
    setError('');
    try {
      const updated = await selectCalendar(appId, calendar.connection_id, calendar.id, {
        selected: checked,
        syncEnabled: checked,
      });
      setCalendars((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      notifyCalendarDataChanged(appId, 'calendars');
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : 'Calendar selection failed.');
    } finally {
      setActiveOperation('');
    }
  }

  async function syncConnection(connection: CalendarConnection) {
    if (!connection.id) {
      return;
    }
    setActiveOperation(connection.id);
    setError('');
    try {
      await syncCalendar(appId, connection.id);
      await refreshCalendarState();
      notifyCalendarDataChanged(appId, 'events');
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : 'Calendar sync failed.');
    } finally {
      setActiveOperation('');
    }
  }

  function selectTreeNode(node: CalendarTreeNode) {
    if (node.type === 'account') {
      return;
    }
    if (node.type === 'calendar' && node.calendar && activeOperation !== node.calendar.id) {
      void toggleRemoteCalendar(node.calendar, node.calendar.sync_enabled === false);
    }
  }

  return (
    <main className="calendar-sidebar-widget">
      {error ? <p className="calendar-sidebar-empty">{error}</p> : null}

      <div className="calendar-sidebar-list calendar-sidebar-tree-list">
        {isLoading ? (
          <AccountSkeleton />
        ) : (
          <TreeProvider
            animateExpand
            className="calendar-folder-tree"
            defaultExpandedIds={defaultExpandedIds}
            indent={18}
            key={treeProviderKey}
            onSelectionChange={() => undefined}
            selectedIds={selectedNodeIds}
          >
            <TreeView>
              {accountTreeNodes.map((node, index) => (
                <CalendarTreeNodeView
                  activeOperation={activeOperation}
                  isLast={index === accountTreeNodes.length - 1}
                  key={node.id}
                  level={0}
                  node={node}
                  onSelect={selectTreeNode}
                  onSyncConnection={syncConnection}
                />
              ))}
            </TreeView>
          </TreeProvider>
        )}
      </div>
    </main>
  );
}

function CalendarTreeNodeView({ node, level, isLast, onSelect, onSyncConnection, activeOperation }: {
  activeOperation: string;
  isLast: boolean;
  level: number;
  node: CalendarTreeNode;
  onSelect: (node: CalendarTreeNode) => void;
  onSyncConnection: (connection: CalendarConnection) => Promise<void>;
}) {
  const hasChildren = node.children.length > 0 || Boolean(node.type === 'account' && node.account?.provider !== 'local');
  const label = node.status && node.status !== 'connected' ? `${node.label} (${node.status})` : node.label;
  const isCalendarEnabled = node.calendar?.sync_enabled !== false;
  const icon = node.type === 'account'
    ? <CircleUserRound className="h-4 w-4" />
    : isCalendarEnabled
      ? <SquareCheck className="calendar-folder-tree-filter-icon is-active h-4 w-4" />
      : <Square className="calendar-folder-tree-filter-icon h-4 w-4" />;

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={node.calendar?.sync_enabled === false ? 'calendar-folder-tree-muted' : ''}
        onClick={() => {
          onSelect(node);
        }}
      >
        <TreeExpander hasChildren={hasChildren} />
        <TreeIcon hasChildren={hasChildren} icon={icon} />
        <TreeLabel title={node.title}>{node.loading ? `${label}...` : label}</TreeLabel>
        {node.type === 'account' && node.account?.connection ? (
          <button
            aria-label={`Sync ${node.label}`}
            className="calendar-folder-tree-sync"
            disabled={activeOperation === node.account.id}
            onClick={(event) => {
              event.stopPropagation();
              void onSyncConnection(node.account!.connection!);
            }}
            type="button"
          >
            <RefreshCw className={activeOperation === node.account.id ? 'is-spinning' : ''} aria-hidden="true" />
          </button>
        ) : null}
      </TreeNodeTrigger>
      <TreeNodeContent hasChildren={hasChildren}>
        {node.children.length === 0 && node.type === 'account' && node.account?.provider !== 'local' ? (
          <TreeNode isLast level={level + 1} nodeId={`${node.id}:empty`}>
            <TreeNodeTrigger className="calendar-folder-tree-status">
              <TreeExpander hasChildren={false} />
              <TreeIcon hasChildren={false} icon={<TriangleAlert className="calendar-folder-tree-alert-icon h-4 w-4" />} />
              <TreeLabel title="Expand to sync this account">Sync this account to load calendars.</TreeLabel>
            </TreeNodeTrigger>
          </TreeNode>
        ) : null}
        {node.children.map((child, index) => (
          <CalendarTreeNodeView
            isLast={index === node.children.length - 1}
            key={child.id}
            level={level + 1}
            node={child}
            activeOperation={activeOperation}
            onSelect={onSelect}
            onSyncConnection={onSyncConnection}
          />
        ))}
      </TreeNodeContent>
    </TreeNode>
  );
}

function AccountSkeleton() {
  return (
    <div className="calendar-sidebar-skeleton" role="status" aria-label="Calendar accounts are loading">
      {Array.from({ length: 5 }).map((_, index) => (
        <div className={`calendar-sidebar-skeleton__row depth-${Math.min(index, 3)}`} key={index} aria-hidden="true">
          <span className="calendar-sidebar-skeleton__expander" />
          <span className="calendar-sidebar-skeleton__icon" />
          <span className="calendar-sidebar-skeleton__copy">
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

function buildCalendarTree(accounts: AccountGroup[], activeOperation: string): CalendarTreeNode[] {
  return accounts.map((account) => ({
    account,
    children: account.calendars.map((calendar) => ({
      calendar,
      children: [],
      id: calendarIdentity(calendar),
      label: calendar.summary || calendar.provider_calendar_id,
      status: calendar.sync_enabled === false ? 'disabled' : calendar.primary ? 'primary' : calendar.access_role || 'calendar',
      title: calendar.primary ? 'Primary calendar' : calendar.access_role || calendar.provider_calendar_id,
      type: 'calendar',
    })),
    id: calendarAccountIdentity(account.id),
    label: account.name,
    loading: activeOperation === account.id,
    status: account.provider === 'local' ? 'connected' : account.status || 'connected',
    title: `${account.provider === 'local' ? 'Local calendar' : account.status || 'Google Calendar'} • ${account.eventCount} events`,
    type: 'account',
  }));
}

function collectDefaultExpandedIds(node: CalendarTreeNode) {
  const ids: string[] = [];

  function visit(current: CalendarTreeNode) {
    if (current.children.length || current.type === 'account' && current.account?.provider !== 'local') {
      ids.push(current.id);
    }
    current.children.forEach(visit);
  }

  visit(node);
  return ids;
}

function calendarAccountIdentity(accountId: string) {
  return `calendar-account:${accountId}`;
}

function calendarIdentity(calendar: CalendarRemoteCalendar) {
  return `calendar:${calendar.connection_id}:${calendar.id}`;
}

function buildAccountGroups(events: Event[], connections: CalendarConnection[], calendars: CalendarRemoteCalendar[]): AccountGroup[] {
  const localEvents = events.filter((event) => calendarAccountFilterValues(event).includes('calendar'));
  const groups: AccountGroup[] = [
    {
      id: 'calendar',
      name: 'Local',
      provider: 'local',
      status: 'connected',
      calendars: [],
      eventCount: localEvents.length,
    },
  ];
  connections
    .slice()
    .sort((left, right) => accountName(left).localeCompare(accountName(right)))
    .forEach((connection) => {
      const accountId = connection.id || connection.account_id || accountName(connection);
      groups.push({
        id: accountId,
        name: accountName(connection),
        provider: connection.provider || 'google',
        status: connection.status || 'connected',
        connection,
        calendars: calendars.filter((calendar) => calendar.connection_id === connection.id),
        eventCount: events.filter((event) => calendarAccountFilterValues(event).includes(accountId)).length,
      });
    });
  return groups;
}

function accountName(connection: CalendarConnection) {
  return connection.account_label || connection.account_id || connection.id || 'Google Calendar';
}

function notifyCalendarDataChanged(appId: string, resource: string) {
  window.parent?.postMessage({ type: 'maverick.app.data-changed', owner_app_id: appId, resource }, window.location.origin);
}

createRoot(document.getElementById('calendar-sidebar-root') as HTMLElement).render(<CalendarSidebarWidget />);
