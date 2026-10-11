import { createRoot } from 'react-dom/client';
import { CalendarSidebar } from './CalendarSidebar';
import './styles.css';

createRoot(document.getElementById('calendar-sidebar-root') as HTMLElement).render(<CalendarSidebar />);
