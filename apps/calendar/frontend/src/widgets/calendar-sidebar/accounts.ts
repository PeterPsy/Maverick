import type { CalendarConnection, CalendarRemoteCalendar, Event } from '../../components/ui/calendar-types';
import { calendarAccountConnections, calendarAccountFilterValues } from '../../components/ui/calendar-utils';

export type AccountGroup = {
  id: string;
  name: string;
  provider: 'local' | string;
  status: string;
  connection?: CalendarConnection;
  calendars: CalendarRemoteCalendar[];
  eventCount: number;
};

export function buildAccountGroups(events: Event[], connections: CalendarConnection[], calendars: CalendarRemoteCalendar[], localCount?: number): AccountGroup[] {
  const localEvents = events.filter((event) => calendarAccountFilterValues(event).includes('calendar'));
  const groups: AccountGroup[] = [
    {
      id: 'calendar',
      name: 'Local',
      provider: 'local',
      status: 'connected',
      calendars: [],
      eventCount: localCount ?? localEvents.length,
    },
  ];
  calendarAccountConnections(connections)
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
        eventCount: connection.event_count ?? events.filter((event) => calendarAccountFilterValues(event).includes(accountId)).length,
      });
    });
  return groups;
}

function accountName(connection: CalendarConnection) {
  return connection.account_label || connection.account_id || connection.id || 'Google Calendar';
}
