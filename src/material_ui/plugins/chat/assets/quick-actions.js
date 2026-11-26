// Schnellaktionen (Chips und Slash-Befehle), eigene Prompts und Hilfen fuer den Chat (reine Funktionen).

export const KINDS = ["worksheet", "mini", "solution", "slide", "other"];

// Spiegelt rules.kind_for_path (Backend); nur fuer die Auswahl der Chips.
export function kindForPath(path) {
  const name = String(path ?? "").split("/").pop().toLowerCase();
  if (!name) return null;
  if (/^(\d+\s+)?slide\.qmd$/.test(name)) return "slide";
  if (name.includes("loesung") || name.includes("lösung")) return "solution";
  if (name.startsWith("ab_mini_")) return "mini";
  if (name.startsWith("ab_")) return "worksheet";
  return "other";
}

export const BUILTIN_ACTIONS = [
  {
    id: "check", title: "Konventionen prüfen und beheben", kinds: KINDS,
    prompt: "Prüfe das Dokument mit check_document gegen die Projektregeln und schlage Korrekturen für alle Befunde vor.",
  },
  {
    id: "solution", title: "Lösung erstellen", kinds: ["worksheet", "mini"],
    prompt: "Erstelle zu diesem Blatt ein Lösungsblatt als neue Datei neben diesem Blatt (propose_new_document, Dateiname mit Zusatz _loesung). Beachte die Lösungsregeln.",
  },
  {
    id: "afb", title: "AFB kennzeichnen", kinds: ["worksheet", "mini"],
    prompt: "Kennzeichne die Aufgaben nach Anforderungsbereichen (AFB I fett, AFB II normal, AFB III rot mit .zusatz) und ordne sie von I nach III; AFB III nur sparsam. Schlage die Änderungen vor.",
  },
  {
    id: "variant", title: "Parallelversion erstellen", kinds: ["worksheet", "mini"],
    prompt: "Erstelle eine Parallelversion dieses Blatts mit gleichen Aufgabentypen und anderen Zahlen als neue Datei (propose_new_document, Dateiname mit Zusatz _b).",
  },
  {
    id: "mini", title: "Mini-AB daraus machen", kinds: ["worksheet"],
    prompt: "Mache aus den wichtigsten Aufgaben ein Mini-Arbeitsblatt (Vorderseite kurze Übungen, Rückseite Knobelaufgabe mit gedrehter Lösung) als neue Datei mit Präfix ab_mini_.",
  },
  {
    id: "slim", title: "Folien sparsamer texten", kinds: ["slide"],
    prompt: "Kürze den Text auf den Folien: pro Folie eine Skizze oder ein Modell-Kürzel, Gesprächsimpulse und Reflexionsfragen nur als HTML-Kommentar. Schlage die Änderungen vor.",
  },
  {
    id: "explain", title: "Erklärungen ergänzen", kinds: ["solution"],
    prompt: "Ergänze Rechenwege, Zusammenhänge und typische Fehler in kurzen, schülerfreundlichen Absätzen; Ergebnisse mit .loesung hervorheben.",
  },
  {
    id: "summary", title: "Zusammenfassen", kinds: ["other"],
    prompt: "Fasse den Inhalt dieses Dokuments in fünf Stichpunkten zusammen.",
  },
];

// Eigene Prompts (kinds leer = fuer jede Dokumentart). Ohne offenes Dokument erscheinen nur diese.
export function actionsFor(path, custom = []) {
  const kind = kindForPath(path);
  const own = custom.filter((item) => !item.kinds?.length || (kind && item.kinds.includes(kind)))
    .map((item, index) => ({ id: `custom-${index}`, title: item.title, prompt: item.prompt, custom: true }));
  const builtin = kind ? BUILTIN_ACTIONS.filter((item) => item.kinds.includes(kind)) : [];
  return [...builtin, ...own];
}

// Vorschlaege fuer "/..."; trifft Titel am Anfang eines Wortes zuerst.
export function filterSlash(input, actions) {
  if (!input.startsWith("/") || input.includes("\n")) return [];
  const query = input.slice(1).trim().toLowerCase();
  if (!query) return actions;
  const scored = [];
  for (const action of actions) {
    const title = action.title.toLowerCase();
    const index = title.split(/\s+/).findIndex((word) => word.startsWith(query));
    if (index >= 0) scored.push([index, action]);
    else if (title.includes(query)) scored.push([99, action]);
  }
  return scored.sort((a, b) => a[0] - b[0]).map(([, action]) => action);
}

// "Titel [worksheet,slide] | Prompt" je Zeile; Zeilen mit # sind Kommentare.
export function parseCustomPrompts(text) {
  const prompts = [];
  const errors = [];
  String(text ?? "").split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    const separator = line.indexOf("|");
    if (separator < 1 || !line.slice(separator + 1).trim()) {
      errors.push(`Zeile ${index + 1}: Format „Titel | Prompt“ erwartet.`);
      return;
    }
    let title = line.slice(0, separator).trim();
    const kinds = [];
    let valid = true;
    const tag = /\[([a-z,\s]*)\]\s*$/.exec(title);
    if (tag) {
      title = title.slice(0, tag.index).trim();
      for (const kind of tag[1].split(",").map((part) => part.trim()).filter(Boolean)) {
        if (!KINDS.includes(kind)) {
          errors.push(`Zeile ${index + 1}: unbekannte Art „${kind}“ (erlaubt: ${KINDS.join(", ")}).`);
          valid = false;
        } else kinds.push(kind);
      }
    }
    if (!title) { errors.push(`Zeile ${index + 1}: Titel fehlt.`); valid = false; }
    if (valid) prompts.push({ title, prompt: line.slice(separator + 1).trim(), kinds });
  });
  return { prompts, errors };
}

export function formatCustomPrompts(prompts) {
  return prompts.map((item) => `${item.title}${item.kinds?.length ? ` [${item.kinds.join(",")}]` : ""} | ${item.prompt}`).join("\n");
}

// -- Datenschutz ---------------------------------------------------------------------------------

export const PROVIDER_OPERATORS = { claude: "Anthropic", codex: "OpenAI", mistral: "Mistral AI" };

export function operatorFor(providerId) {
  return PROVIDER_OPERATORS[providerId] || providerId || "dem Anbieter";
}

// Vertrauliche Ordner (Klausuren): vor dem Versand wird nachgefragt.
export function isSensitivePath(path) {
  return /(^|\/)klausur[^/]*(\/|$)/i.test(String(path ?? ""));
}

// Aufbereitung eines abgelehnten Aenderungsvorschlags fuer "Neu auf aktuellem Stand anfordern".
export function retryPrompt(edit) {
  const clip = (text, max) => (text.length > max ? `${text.slice(0, max)} …` : text);
  return "Der Editorinhalt hat sich seit deinem Vorschlag geändert. Wende die folgende Änderung auf den aktuellen Stand an "
    + `(propose_document_edit):\nVorher:\n${clip(String(edit.old_text ?? ""), 400)}\nNachher:\n${clip(String(edit.new_text ?? ""), 800)}`;
}
