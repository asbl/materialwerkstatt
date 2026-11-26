export function formatTimestamp(seconds) {
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}


export function loadAutoRenderPreference() {
  try {
    return localStorage.getItem("material-ui:auto-render") !== "false";
  } catch (error) {
    return true;
  }
}

export function saveAutoRenderPreference(value) {
  try {
    localStorage.setItem("material-ui:auto-render", value ? "true" : "false");
  } catch (error) {
    // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
  }
}

export function loadTagYearFilterPreference() {
  try {
    return localStorage.getItem("material-ui:tag-year-filter") || "";
  } catch (error) {
    return "";
  }
}

export function saveTagYearFilterPreference(value) {
  try {
    localStorage.setItem("material-ui:tag-year-filter", value);
  } catch (error) {
    // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
  }
}

export function loadAutoSavePreference() {
  try {
    return localStorage.getItem("material-ui:auto-save") !== "false";
  } catch (error) {
    return true;
  }
}

export function saveAutoSavePreference(value) {
  try {
    localStorage.setItem("material-ui:auto-save", value ? "true" : "false");
  } catch (error) {
    // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
  }
}



export function normalizeSearch(value) {
  return String(value)
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "");
}

export function slug(value) {
  return normalizeSearch(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "material";
}

export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function loadLastDocumentPreference() {
  try {
    return localStorage.getItem("material-ui:last-document") || "";
  } catch (error) {
    return "";
  }
}

export function saveLastDocumentPreference(path) {
  try {
    localStorage.setItem("material-ui:last-document", path || "");
  } catch (error) {
    // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
  }
}

export function loadLastMaterialContext() {
  try {
    return JSON.parse(localStorage.getItem("material-ui:new-doc-context") || "null") || {};
  } catch (error) {
    return {};
  }
}

export function saveLastMaterialContext({ subject, grade, topic }) {
  try {
    localStorage.setItem("material-ui:new-doc-context", JSON.stringify({ subject, grade, topic }));
  } catch (error) {
    // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
  }
}


// Gemeinsame Typanzeige für Navigation und Suchtreffer; Lösungen haben Vorrang.
export function materialIcon(entry = {}) {
  const kind = normalizeSearch(entry.kind || "");
  const name = normalizeSearch((entry.name || entry.path || "").split("/").pop());
  if (kind === "notiz" || /^notiz_.*\.md$/.test(name)) return "note";
  if (entry.solution || kind === "loesung" || (entry.tags || []).includes("Lösung") || name.includes("loesung")) return "solution";
  if (kind === "deck" || /praesentation|folie|slide/.test(kind) || /(?:^|[ _-])slides?\.qmd$/.test(name) || name.endsWith(".excalidraw")) return "slides";
  if (/^ab[_-]mini[_-]/.test(name) || /^mini[ _-]?(?:ab|arbeitsblatt)$/.test(kind)) return "mini-worksheet";
  if (/arbeitsblatt|aufgabenblatt/.test(kind) || /^ab[_-]/.test(name)) return "worksheet";
  return "file";
}

// Resolve notes independently of solution pairing, including notes on solutions.
export function worksheetNotesFor(entries, sourcePath) {
  const normalize = path => path.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const sourceStem = normalize(sourcePath.replace(/\.qmd$/i, ""));
  const canonical = sourcePath.replace(/\.qmd$/i, "-notizen.md");
  return entries.filter(entry => !entry.directory && materialIcon(entry) === "note"
    && /[-_](?:notizen|notiz)\.md$/i.test(entry.path)
    && normalize(entry.path.replace(/[-_](?:notizen|notiz)\.md$/i, "")) === sourceStem)
    .sort((a, b) => Number(b.path === canonical) - Number(a.path === canonical)
      || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

// Pair source files only within the same folder; unrelated solutions stay standalone.
// AB-Notizen paaren sich per Namenssuffix (`ab_x-notizen.md` neben `ab_x.qmd`)
// genauso wie Loesungen (`ab_x-loesung.qmd`).
export function pairMaterialEntries(entries) {
  const stem = path => path.replace(/\.qmd$/i, "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[-_](?:loesung|losung)(?:en)?$/i, "");
  const noteStem = path => path.replace(/\.md$/i, "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[-_](?:notizen|notiz)$/i, "");
  const NOTE_SUFFIX = /[-_](?:notizen|notiz)$/i;
  const primaries = new Map(entries.filter(entry => !entry.directory && /\.qmd$/i.test(entry.path) && materialIcon(entry) !== "solution").map(entry => [stem(entry.path), entry]));
  const pairs = new Map();
  const notePairs = new Map();
  const paired = new Set();
  // A shared solution can belong to several worksheets in the same folder.
  for (const primary of primaries.values()) {
    if (!primary.loesung) continue;
    const folder = primary.path.slice(0, primary.path.lastIndexOf('/') + 1);
    const solution = entries.find(entry => entry.path === folder + primary.loesung && materialIcon(entry) === "solution");
    if (!solution) continue;
    pairs.set(primary.path, [solution]);
    paired.add(solution.path);
  }
  for (const entry of entries) {
    if (entry.directory) continue;
    if (/\.qmd$/i.test(entry.path) && materialIcon(entry) !== "solution") continue;
    const solution = /\.qmd$/i.test(entry.path) && materialIcon(entry) === "solution";
    const note = /\.md$/i.test(entry.path) && materialIcon(entry) === "note" && NOTE_SUFFIX.test(entry.path.replace(/\.md$/i, ""));
    if (!solution && !note) continue;
    const primary = primaries.get((solution ? stem : noteStem)(entry.path));
    if (!primary) continue;
    if (solution && primary.loesung && pairs.has(primary.path)) continue;
    const group = (solution ? pairs : notePairs);
    if (!group.has(primary.path)) group.set(primary.path, []);
    group.get(primary.path).push(entry);
    paired.add(entry.path);
  }
  return entries.filter(entry => !paired.has(entry.path)).map(entry => ({ entry, solutions: pairs.get(entry.path) || [], notes: notePairs.get(entry.path) || [] }));
}

export function materialDisplay(entry) {
  const type = materialIcon(entry);
  const kind = { note: "Notiz", "mini-worksheet": "Mini-AB", worksheet: "Arbeitsblatt", solution: "Lösung", slides: "Präsentation", file: entry.kind || "Material" }[type];
  const title = (entry.title || entry.name || entry.path).replace(/^(?:(?:AB|Arbeitsblatt|Slides?|Folien|Präsentation|Lösung(?:en)?|Musterlösung(?:en)?)\s*[:–-]\s*)+/i, "");
  return { type, kind, title };
}
