// Gemeinsamer Zustand der Kalender-Ansichten (ein Objekt, damit alle Module dieselbe Instanz teilen).


export const TODAY_MODE_KEY = "material-ui:kalender-day-mode";

function loadTodayMode() {
  try {
    return localStorage.getItem(TODAY_MODE_KEY) === "morgen" ? "morgen" : "heute";
  } catch {
    return "heute";
  }
}

export const store = {
  status: null,
  events: [],
  agendaTasks: [],
  eventsFrom: "",
  eventsTo: "",
  pending: null,
  monthCursor: null,
  agendaStart: null,
  agendaDays: 14,
  todayMode: loadTodayMode(),
  statusLine: null,
  todayHandle: null,
};

export const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

export function today() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

// Die Heute-Seite kann zwischen heute und morgen umschalten (Unterrichtsvorbereitung).
export function viewDay() {
  const base = today();
  if (store.todayMode === "morgen") return new Date(base.getFullYear(), base.getMonth(), base.getDate() + 1);
  return base;
}

export function modeLabel() {
  return store.todayMode === "morgen" ? "morgen" : "heute";
}

export function modeTitle() {
  return store.todayMode === "morgen" ? "Morgen" : "Heute";
}