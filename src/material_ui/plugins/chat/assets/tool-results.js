// Aufbereitung von Werkzeugaufrufen und -ergebnissen fuer das Chat-Panel (reine Funktionen).

const KNOWN = {
  search_wissen: "Wissensbasis durchsuchen",
  search_unterricht: "Unterricht durchsuchen",
  read_file: "Datei lesen",
  show_task_image: "Aufgabenbild ansehen",
  propose_document_edit: "Änderung vorschlagen",
  check_document: "Regeln prüfen",
  read_unit: "Einheit lesen",
  list_templates: "Vorlagen auflisten",
  propose_new_document: "Neue Datei vorschlagen",
};
// Werkzeuge der CLI selbst; sie laufen in der Sandbox und werden deshalb besonders gekennzeichnet.
const BUILTIN = { shell: "Shell (Sandbox)", "file_system.bash": "Shell (Sandbox)", "file_system.read_file": "Datei lesen (Sandbox)" };
const INTERNAL = new Set(["search_tool_functions"]);

// mcp__wissen__search_wissen, mcp_wissen.search_wissen und search_wissen -> search_wissen
export function baseToolName(name) {
  const text = String(name ?? "");
  if (BUILTIN[text]) return text;
  const afterDoubleUnderscore = text.includes("__") ? text.slice(text.lastIndexOf("__") + 2) : text;
  return afterDoubleUnderscore.startsWith("mcp_wissen.") ? afterDoubleUnderscore.slice("mcp_wissen.".length) : afterDoubleUnderscore;
}

export const isInternalTool = (name) => INTERNAL.has(baseToolName(name));
export const isBuiltinTool = (name) => !KNOWN[baseToolName(name)] && !INTERNAL.has(baseToolName(name));
export const toolLabel = (name) => KNOWN[baseToolName(name)] || BUILTIN[baseToolName(name)] || String(name ?? "Werkzeug");

// Fasst die unterschiedlichen Ergebnisformen der CLIs zu einem Text zusammen.
export function toolOutputText(output) {
  if (output == null) return "";
  if (typeof output === "string") return output;
  if (Array.isArray(output)) return output.map(toolOutputText).filter(Boolean).join("\n");
  if (typeof output === "object") {
    if (Array.isArray(output.content)) return toolOutputText(output.content);
    if (typeof output.text === "string") return output.text;
    if (output.structured_content) return toolOutputText(output.structured_content);
    return JSON.stringify(output);
  }
  return String(output);
}

export function isToolError(event) {
  if (event?.is_error === true) return true;
  return /^\s*(Error executing tool|Error:|Fehler:)/i.test(toolOutputText(event?.tool_output));
}

// Alle JSON-Werte eines Textes (ein Wert, eine Liste oder mehrere aneinandergereihte Objekte).
export function parseJsonValues(text) {
  const source = String(text ?? "").trim();
  if (!source) return [];
  try {
    const value = JSON.parse(source);
    return Array.isArray(value) ? value : [value];
  } catch { /* mehrere Objekte hintereinander: einzeln herausloesen */ }
  const values = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
    } else if (char === '"') inString = true;
    else if (char === "{") { if (depth === 0) start = i; depth += 1; }
    else if (char === "}" && depth > 0) {
      depth -= 1;
      if (depth === 0) {
        try { values.push(JSON.parse(source.slice(start, i + 1))); } catch { /* ignorieren */ }
      }
    }
  }
  return values;
}

export function sourceUrl(path, page) {
  const base = `/api/chat/source?path=${encodeURIComponent(path)}`;
  return Number.isInteger(page) && page > 0 ? `${base}#page=${page}` : base;
}

// Treffer der Such- und Lesewerkzeuge als {path, page, title, snippet, openable}.
export function extractHits(tool, output) {
  const name = baseToolName(tool);
  if (!["search_wissen", "search_unterricht", "read_file"].includes(name)) return [];
  const hits = [];
  for (const value of parseJsonValues(toolOutputText(output))) {
    if (!value || typeof value !== "object") continue;
    const path = value.pfad || value.path;
    if (typeof path !== "string" || !path) continue;
    const isKnowledge = name === "search_wissen";
    const fullPath = isKnowledge && !path.startsWith("wissen/") ? `wissen/${path}` : path;
    hits.push({
      path: fullPath,
      page: Number.isInteger(value.seite) ? value.seite : (Number.isInteger(value.page) ? value.page : null),
      title: typeof value.title === "string" ? value.title : "",
      snippet: String(value.ausschnitt || value.snippet || "").slice(0, 240),
      // Unterrichtsmaterial oeffnet im Editor, Wissens-PDFs im Browser (an der gefundenen Seite).
      openable: /^unterricht\/.+\.(qmd|md|tex)$/i.test(fullPath),
      sourceUrl: /^wissen\/.+\.pdf$/i.test(fullPath) ? sourceUrl(fullPath, value.seite ?? value.page) : "",
    });
  }
  return hits;
}
