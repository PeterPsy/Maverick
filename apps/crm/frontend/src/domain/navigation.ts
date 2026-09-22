import { LayoutDashboard, ListTodo, MessageSquare, CalendarDays, Users, Building2, Handshake, Receipt, Radar, Inbox, FileText, AudioLines, ShieldCheck, Rows3, Columns3, BarChart3, Download, Boxes, Megaphone, Settings2 } from 'lucide-react';
import { ViewId } from './types';

export const productNavigation: { page: ViewId; label: string; icon: typeof Users; secondary?: boolean }[] = [
  { page: 'overview', label: 'Dashboard', icon: LayoutDashboard },
  { page: 'leads', label: 'Leads', icon: Users },
  { page: 'today', label: 'Tasks', icon: ListTodo },
  { page: 'conversations', label: 'Threads', icon: MessageSquare },
  { page: 'calendar', label: 'Calendar', icon: CalendarDays },
  { page: 'people', label: 'People', icon: Users },
  { page: 'companies', label: 'Companies', icon: Building2 },
  { page: 'deals', label: 'Deals', icon: Handshake },
  { page: 'expenses', label: 'Expenses', icon: Receipt },
  { page: 'intelligence', label: 'Intelligence', icon: Radar },
  { page: 'proposals', label: 'Proposals', icon: Inbox },
  { page: 'briefs', label: 'Brief archive', icon: FileText, secondary: true },
  { page: 'transcripts', label: 'Transcripts', icon: AudioLines, secondary: true },
  { page: 'quality', label: 'Data quality', icon: ShieldCheck, secondary: true },
  { page: 'records', label: 'Records', icon: Rows3, secondary: true },
  { page: 'pipeline', label: 'Pipeline', icon: Columns3, secondary: true },
  { page: 'reports', label: 'Reports', icon: BarChart3, secondary: true },
  { page: 'objects', label: 'Custom objects', icon: Boxes, secondary: true },
  { page: 'campaigns', label: 'Campaigns', icon: Megaphone, secondary: true },
  { page: 'import', label: 'Import', icon: Download, secondary: true },
  { page: 'integrations', label: 'Connections', icon: Settings2, secondary: true },
];
