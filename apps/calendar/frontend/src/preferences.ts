export interface CalendarPreferences {
  locale: "it-IT" | "en-US";
  weekStartsOn: 0 | 1;
  hour12: boolean;
  workStart: string;
  workEnd: string;
  bufferMinutes: number;
  workDays: number[];
}
const KEY = "maverick.calendar.preferences";
export function readPreferences(): CalendarPreferences {
  const defaults: CalendarPreferences = {
    locale: (navigator.language || "en-US").startsWith("it") ? "it-IT" : "en-US",
    weekStartsOn: 1,
    hour12: false,
    workStart: "09:00",
    workEnd: "18:00",
    bufferMinutes: 0,
    workDays: [1, 2, 3, 4, 5],
  };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return defaults;
  }
}
export function savePreferences(patch: Partial<CalendarPreferences>) {
  const value = { ...readPreferences(), ...patch };
  localStorage.setItem(KEY, JSON.stringify(value));
  window.dispatchEvent(new Event("calendar-preferences-changed"));
  return value;
}
const it: Record<string, string> = {
  "Loading calendar…": "Caricamento calendario…",
  Syncing: "Sincronizzazione",
  "Clear filters": "Cancella filtri",
  Accounts: "Account",
  Colors: "Colori",
  Categories: "Categorie",
  Filters: "Filtri",
  "Clear all": "Cancella tutti",
  Clear: "Cancella",
  Confirmed: "Confermato",
  Tentative: "Provvisorio",
  Cancelled: "Annullato",
  "Read only": "Sola lettura",
  "Local calendar": "Calendario locale",
  Local: "Locale",
  "Primary calendar": "Calendario principale",
  Meeting: "Riunione",
  Task: "Attività",
  Personal: "Personale",
  Blue: "Blu",
  Green: "Verde",
  Red: "Rosso",
  Purple: "Viola",
  Yellow: "Giallo",
  Orange: "Arancione",
  Pink: "Rosa",
  Gray: "Grigio",
  "Never synced": "Mai sincronizzato",
  "Data needs updating": "Dati da aggiornare",
  "No times proposed yet": "Nessun orario proposto",
  "Sync is partial; continue syncing to fetch remaining pages.":
    "Sincronizzazione parziale; prosegui per caricare le pagine rimanenti.",
  "Unable to load event": "Impossibile caricare l’evento",
  "Event could not be saved.": "Impossibile salvare l’evento.",
  "Title is required.": "Il titolo è obbligatorio.",
  "Start time is required.": "L’inizio è obbligatorio.",
  "End time is required.": "La fine è obbligatoria.",
  "End time must be after start time.":
    "La fine deve essere successiva all’inizio.",
  "Use Google default reminders": "Usa i promemoria predefiniti Google",
  "Select entire series to transfer this recurring event.":
    "Seleziona intera serie per trasferire questo evento ricorrente.",
  Today: "Oggi",
  Month: "Mese",
  Week: "Settimana",
  Day: "Giorno",
  List: "Agenda",
  Time: "Ora",
  "New event": "Nuovo evento",
  "Search events...": "Cerca eventi...",
  "No events found": "Nessun evento",
  "Create Event": "Crea evento",
  "Event Details": "Dettagli evento",
  Title: "Titolo",
  Description: "Descrizione",
  "Start Time": "Inizio",
  "End Time": "Fine",
  Calendar: "Calendario",
  "Account / Calendar": "Account / Calendario",
  Category: "Categoria",
  Color: "Colore",
  Tags: "Etichette",
  Save: "Salva",
  "Saving...": "Salvataggio...",
  Delete: "Elimina",
  Close: "Chiudi",
  Location: "Luogo",
  Attendees: "Partecipanti",
  Timezone: "Fuso orario",
  Status: "Stato",
  "All day": "Tutto il giorno",
  Busy: "Occupa tempo",
  Free: "Disponibile",
  "Advanced options": "Opzioni avanzate",
  Recurrence: "Ricorrenza",
  Reminder: "Promemoria",
  None: "Nessuna",
  Daily: "Giornaliera",
  Weekly: "Settimanale",
  Monthly: "Mensile",
  Yearly: "Annuale",
  "Repeat count": "Numero ripetizioni",
  "This occurrence": "Questa occorrenza",
  "This and following": "Questa e le successive",
  "Entire series": "Intera serie",
  "Find a time": "Trova un orario",
  "Working hours": "Orario lavorativo",
  "Buffer minutes": "Pausa tra eventi (minuti)",
  "Use this time": "Usa questo orario",
  Settings: "Preferenze",
  Language: "Lingua",
  "First weekday": "Primo giorno",
  "Time format": "Formato orario",
  Monday: "Lunedì",
  Sunday: "Domenica",
  Previous: "Precedente",
  Next: "Successivo",
  "Clear search": "Cancella ricerca",
  "Search all calendars": "Cerca in tutti i calendari",
  From: "Dal",
  To: "Al",
  "Load more": "Carica altri",
  "Known local events only; invitee calendars may be incomplete.":
    "Solo eventi locali conosciuti; i calendari degli invitati possono essere incompleti.",
  Show: "Mostra",
  Sync: "Sincronizza",
  Availability: "Disponibilità",
  "Sync now": "Sincronizza ora",
  Undo: "Annulla",
  "Discard unsaved changes?": "Scartare le modifiche non salvate?",
  "Event deleted": "Evento eliminato",
  "Keep draft and retry with latest revision":
    "Mantieni la bozza e riprova sulla versione aggiornata",
  "Reload latest event": "Carica la versione aggiornata",
  "Another version is available. Your draft has been kept.":
    "È disponibile una nuova versione. La bozza è stata conservata.",
  "End date is exclusive": "La data finale è esclusiva",
  Connect: "Connetti",
  Connecting: "Connessione...",
  "Local reminders are saved in Maverick notifications, even when Calendar is closed.":
    "I promemoria locali vengono conservati nelle notifiche Maverick, anche con Calendar chiuso.",
  "Overlapping events": "Eventi sovrapposti",
  "Event title": "Titolo evento",
  "Event description": "Descrizione evento",
};
export function t(text: string): string {
  return readPreferences().locale === "it-IT" ? it[text] || text : text;
}
export function formatCalendarDate(
  date: Date,
  options: Intl.DateTimeFormatOptions,
) {
  return date.toLocaleDateString(readPreferences().locale, options);
}
export function formatCalendarTime(date: Date) {
  return date.toLocaleTimeString(readPreferences().locale, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: readPreferences().hour12,
  });
}
