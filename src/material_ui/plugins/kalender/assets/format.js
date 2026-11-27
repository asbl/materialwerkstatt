// Reine Datums-, Text- und Farbhilfen der Kalender-Ansichten (ohne eigenen Zustand).

import { escapeHtml } from "/static/ui-utils.js";
import { today } from "./store.js";

export function isoDate(value) {
  const year = String(value.getFullYear()).padStart(4, "0");
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function parseIsoDate(text) {
  const parts = String(text).split("-");
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
}

export function firstOfMonth(cursor) {
  return new Date(cursor.getFullYear(), cursor.getMonth(), 1);
}

export function addMonths(cursor, amount) {
  return new Date(cursor.getFullYear(), cursor.getMonth() + amount, 1);
}

export function dayLabel(date) {
  return date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

export function monthLabel(cursor) {
  return cursor.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
}

export function weekdayHeadingLabel(value) {
  const parts = value.split("-");
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
    .toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" });
}

export function timeLabel(event) {
  if (event.kind === "todo") return "☐ TODO";
  if (event.allDay) return "ganztägig";
  const parts = event.start.split("T");
  return parts[1] ? parts[1].slice(0, 5) : "";
}

export function lessonHint(lesson) {
  if (!lesson || !lesson.start || !lesson.start.includes("T")) return "";
  const start = lesson.start.slice(11, 16);
  const end = (lesson.end || "").slice(11, 16);
  return `Std. ${start}${end ? `–${end}` : ""}${lesson.title ? ` · ${lesson.title}` : ""}`;
}

// Einheitenlink einer Stunde plus je ein Knopf für das im Einsatz genannte Material
// (`unit.materials`, relativ zum Einheitenordner). Der Kern öffnet beides über Ereignisse.
export function unitHintsHtml(units) {
  return (units || []).map(unit => `<button type="button" class="kal-unit-hint" data-kal-unit="${escapeHtml(unit.path)}" title="Unterrichtseinheit öffnen">↳ ${escapeHtml(unit.title)}</button>${(unit.materials || []).map(material => {
    const path = [];
    for (const part of `${unit.path}/${material}`.split('/')) {
      if (part === '..') path.pop();
      else if (part && part !== '.') path.push(part);
    }
    return `<button type="button" class="kal-unit-hint kal-material-hint" data-kal-material="${escapeHtml(path.join('/'))}" title="Material öffnen">${escapeHtml(path.at(-1))}</button>`;
  }).join('')}`).join('');
}

const PALETTE_SIZE = 8;

function kalColor(name) {
  let hash = 0;
  for (const character of String(name)) hash = (hash * 31 + character.charCodeAt(0)) % 997;
  return (hash % PALETTE_SIZE) + 1;
}

export function eventColor(event) {
  return /^#[0-9a-f]{6}$/i.test(event.color || '') ? event.color : `var(--kal-${kalColor(event.calendar)}, var(--accent))`;
}

export function eventChip(event, options = {}) {
  const coveredOnly = options.startDay !== event.startDate;
  const time = coveredOnly ? "" : timeLabel(event);
  const holidayClass = event.holiday ? " kal-holiday" : "";
  return `<span class="kal-chip${holidayClass}" style="--kal-event: ${eventColor(event)}"
    data-event-key="${escapeHtml(event.key)}">${time ? `<span class="kal-chip-time">${escapeHtml(time)}</span>` : ""}<span class="kal-chip-title">${event.holiday ? "Ferien: " : ""}${escapeHtml(event.title)}</span></span>`;
}
export function relativeTaskDate(value) {
  const date = parseIsoDate(value);
  const day = today();
  // Kalendertage statt Stunden zählen, auch über Sommerzeitwechsel hinweg.
  const distance = Math.round((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())
    - Date.UTC(day.getFullYear(), day.getMonth(), day.getDate())) / 86400000);
  if (distance === 0) return 'heute';
  if (distance === 1) return 'morgen';
  if (distance === -1) return 'gestern';
  return date.toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
}
