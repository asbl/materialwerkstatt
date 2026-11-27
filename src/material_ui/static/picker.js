import { materialIcon } from "./ui-utils.js";
import { createFulltextState } from "./fulltext-state.js";

const FULLTEXT_MIN_CHARS = 3;
const FULLTEXT_DEBOUNCE_MS = 300;

export function createPickerController({ search, searchProviders = null, fulltext = createFulltextState(), state, elements, api, escapeHtml, normalizeSearch, selectDocument, assignWorksheet, uiIcon }) {
  const KIND_CHIP_LABELS = {
    "Arbeitsblatt": "Arbeitsblätter",
    "Klausur": "Klausuren",
    "Nachprüfung": "Nachprüfungen",
    "Fördermaterial": "Fördermaterial",
    "Praesentation": "Präsentationen",
    "Planung": "Planung"
  };

  function activeChips() {
    const chips = [{ id: "alle", label: "Unterrichtsmaterial", match: (entry) => !/^(src|docs|build)\//.test(entry.source_path || entry.path) }, { id: "everything", label: "Alle Bereiche", match: () => true }];
    if (state.qmds.some((entry) => entry.area === "unterricht")) {
      chips.push({ id: "unterricht", label: "Unterricht", match: (entry) => entry.area === "unterricht" });
    }
    if (state.qmds.some((entry) => entry.kind === "Kurs (H5P)")) {
      chips.push({ id: "kurse", label: "Kurse", match: (entry) => entry.kind === "Kurs (H5P)" });
    }
    for (const subject of uniqueValues("subject")) {
      chips.push({ id: `subject:${subject}`, label: labelValue(subject), match: (entry) => entry.subject === subject });
    }
    for (const kind of uniqueValues("kind")) {
      if (kind === "Kurs (H5P)" || kind === "Deck") continue;
      chips.push({ id: `kind:${kind}`, label: KIND_CHIP_LABELS[kind] || kind, match: (entry) => entry.kind === kind });
    }
    if (state.qmds.some((entry) => entry.solution)) {
      chips.push({ id: "loesung", label: "Lösungen", match: (entry) => Boolean(entry.solution) });
    }
    return chips;
  }

  function renderFilterChips() {
    const chips = activeChips();
    if (!chips.some((chip) => chip.id === state.activeFilter)) state.activeFilter = "alle";
    elements.filterChips.innerHTML = chips.map((chip) => (
      `<button type="button" class="chip${state.activeFilter === chip.id ? " active" : ""}" data-filter="${escapeHtml(chip.id)}">${escapeHtml(chip.label)}</button>`
    )).join("");
    for (const chip of elements.filterChips.querySelectorAll(".chip")) {
      chip.addEventListener("click", () => {
        state.activeFilter = chip.dataset.filter;
        renderFilterChips();
        scheduleFulltextSearch();
        renderDocumentResults(true);
        openPicker();
      });
    }
  }

  function renderFacetFilters() {
    setSelectOptions(elements.subjectFilter, "Alle Fächer", uniqueValues("subject"));
    setSelectOptions(elements.gradeFilter, "Alle Klassen", uniqueValues("grade").sort(compareGrade));
    setSelectOptions(elements.kindFilter, "Alle Typen", uniqueValues("kind"));
    elements.tagFilterOptions.innerHTML = uniqueTags().map((tag) => `<option value="${escapeHtml(tag)}"></option>`).join("");
    elements.tagFilter.value = state.facetFilters.tag;
    setSelectOptions(elements.pdfFilter, "Alle PDFs", ["with-pdf", "without-pdf"], {
      "with-pdf": "Mit PDF",
      "without-pdf": "Ohne PDF"
    });
    elements.sortFilter.value = state.facetFilters.sort;
  }

  function setSelectOptions(select, emptyLabel, values, labels = {}) {
    const current = select.value || state.facetFilters[facetKeyFor(select)] || "";
    select.innerHTML = [
      `<option value="">${escapeHtml(emptyLabel)}</option>`,
      ...values.filter(Boolean).map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(labels[value] || labelValue(value))}</option>`)
    ].join("");
    select.value = values.includes(current) ? current : "";
    state.facetFilters[facetKeyFor(select)] = select.value;
  }

  function uniqueValues(key) {
    return [...new Set(state.qmds.map((entry) => entry[key]).filter(Boolean))].sort((a, b) => labelValue(a).localeCompare(labelValue(b), "de"));
  }

  function uniqueTags() {
    const tags = new Set();
    for (const entry of state.qmds) {
      for (const tag of entry.tags || []) tags.add(tag);
    }
    return [...tags].sort((first, second) => first.localeCompare(second, "de"));
  }

  function labelValue(value) {
    return String(value).replace(/^klasse-(\d+)$/, "Klasse $1");
  }

  function compareGrade(a, b) {
    const numberA = Number((a.match(/\d+/) || [999])[0]);
    const numberB = Number((b.match(/\d+/) || [999])[0]);
    return numberA - numberB || a.localeCompare(b, "de");
  }

  function facetElements() {
    return {
      subject: elements.subjectFilter,
      grade: elements.gradeFilter,
      kind: elements.kindFilter,
      tag: elements.tagFilter,
      pdf: elements.pdfFilter,
      sort: elements.sortFilter
    };
  }

  function facetKeyFor(select) {
    return Object.entries(facetElements()).find(([, element]) => element === select)?.[0] || "";
  }

  function bindFacetChange(listener) {
    for (const [key, element] of Object.entries(facetElements())) {
      element.addEventListener("change", () => {
        state.facetFilters[key] = element.value;
        listener();
      });
    }
  }

  // Befehlspalette: Eingaben mit ">" suchen statt Material die Befehle der Oberflaeche.
  let commands = [];
  let commandResults = [];

  function registerCommands(list) {
    commands = list;
  }

  function commandQuery() {
    const raw = documentSearchQuery().trimStart();
    return raw.startsWith(">") ? normalizeSearch(raw.slice(1)).trim() : null;
  }

  function renderCommandResults(query, resetActive) {
    const parts = query.split(/\s+/).filter(Boolean);
    commandResults = commands.filter((command) => (
      (!command.available || command.available())
      && parts.every((part) => normalizeSearch(`${command.label} ${command.keywords || ""}`).includes(part))
    ));
    state.filteredQmds = [];
    if (resetActive) state.activeResult = 0;
    state.activeResult = Math.max(0, Math.min(state.activeResult, commandResults.length - 1));
    elements.documentResults.innerHTML = commandResults.length
      ? commandResults.map((command, index) => (
        `<button type="button" id="document-option-${index}" class="document-option command-option${index === state.activeResult ? " active" : ""}" data-command="${escapeHtml(command.id)}" role="option" aria-selected="${index === state.activeResult}">
    <span class="document-title">${command.icon ? uiIcon(command.icon) : ""}${escapeHtml(command.label)}</span>
    ${command.hint ? `<span class="document-meta">${escapeHtml(command.hint)}</span>` : ""}
  </button>`
      )).join("")
      : `<div class="empty-result">Kein Befehl gefunden.</div>`;
    if (commandResults.length) elements.documentResults.setAttribute("aria-activedescendant", `document-option-${state.activeResult}`);
    else elements.documentResults.removeAttribute("aria-activedescendant");
    for (const button of elements.documentResults.querySelectorAll(".command-option")) {
      button.addEventListener("click", () => runCommand(button.dataset.command));
    }
  }

  function runCommand(id) {
    const command = commands.find((candidate) => candidate.id === id);
    if (!command) return;
    closePicker();
    if (search) search.setQuery("");
    else elements.documentSearch.value = "";
    elements.documentSearch.blur();
    command.run();
  }

  function renderDocumentResults(resetActive) {
    const commandText = commandQuery();
    elements.searchOverlay?.classList.toggle("command-mode", commandText !== null);
    if (commandText !== null) {
      renderCommandResults(commandText, resetActive);
      return;
    }
    commandResults = [];
    const terms = normalizeSearch(documentSearchQuery()).split(/\s+/).filter(Boolean);
    const chip = activeChips().find(candidate => candidate.id === state.activeFilter);
    const candidates = new Map(state.qmds.map(entry => [entry.path, { entry, score: scoreDocument(entry, terms) }]));
    const currentKey = searchKey();
    const hits = fulltext.key == null || fulltext.key === currentKey ? fulltext.results || [] : [];
    for (const hit of hits) {
      const previous = candidates.get(hit.path);
      const entry = { ...previous?.entry, ...hit };
      candidates.set(hit.path, { entry, score: Math.max(0, scoreDocument(entry, terms)) + Math.min(9, hit.score || 0) + 1 });
    }
    state.filteredQmds = [...candidates.values()]
      .filter(({ entry, score }) => score > -1 && filterMatches(entry) && (!chip || chip.match(entry)))
      .sort(compareDocumentMatches)
      .slice(0, 80)
      .map(({ entry }) => entry);
    // Keep source, solution and generated deck adjacent; the strongest hit
    // determines the group's position without changing explicit sort orders.
    if (state.facetFilters.sort === "relevance") {
      const groups = new Map();
      for (const entry of state.filteredQmds) {
        const key = materialGroupKey(entry);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(entry);
      }
      state.filteredQmds = [...groups.values()].flat();
    }
    if (resetActive) state.activeResult = 0;
    state.activeResult = Math.max(0, Math.min(state.activeResult, state.filteredQmds.length - 1));
    elements.documentResults.innerHTML = state.filteredQmds.length
      ? state.filteredQmds.map((entry, index) => documentOptionHtml(entry, index)).join("")
      : `<div class="empty-result">Keine Treffer.</div>`;
    if (state.filteredQmds.length) elements.documentResults.setAttribute("aria-activedescendant", `document-option-${state.activeResult}`);
    else elements.documentResults.removeAttribute("aria-activedescendant");
    for (const button of elements.documentResults.querySelectorAll(".document-option")) {
      button.addEventListener("click", () => openResult(state.filteredQmds[Number(button.dataset.result)]));
    }
    for (const button of elements.documentResults.querySelectorAll("[data-assign-result]")) {
      button.addEventListener("click", () => assignWorksheet(state.filteredQmds[Number(button.dataset.assignResult)]));
    }
  }

  function openResult(entry) {
    if (Number.isInteger(entry.page) && entry.page > 0 && entry.path === entry.pdf && /\.pdf$/i.test(entry.path)) {
      window.open(`/api/pdf?path=${encodeURIComponent(entry.path)}#page=${entry.page}`, "_blank", "noopener");
      closePicker();
      return;
    }
    return selectDocument(entry.path, { line: entry.line || null });
  }

  function materialGroupKey(entry) {
    return entry.path.replace(/^build\/artefakte\//, "").replace(/\.(qmd|md|excalidraw)$/, "")
      .replace(/[-_](loesung|loesungen|lösung|lösungen)$/, "");
  }

  function documentOptionHtml(entry, index) {
    const tags = [...new Set([entry.subject, entry.grade && labelValue(entry.grade), entry.kind, entry.solution ? "Lösung" : ""].filter(Boolean))].join(" · ");
    const snippet = entry.snippet
      ? `<span class="document-snippet">${escapeHtml(entry.page ? `Seite ${entry.page} · ` : entry.line ? `Zeile ${entry.line}: ` : "")}${escapeHtml(readableSnippet(entry.snippet))}</span>`
      : "";
    const badge = entry.kind === "Deck"
      ? '<span class="document-fulltext-badge">Deck</span>'
      : entry.snippet
        ? '<span class="document-fulltext-badge">Volltext</span>'
        : "";
    const sourceName = entry.source
      ? (fulltext.sources || []).find((source) => source.id === entry.source)?.name
      : null;
    const sourceBadge = sourceName ? `<span class="document-fulltext-badge">${escapeHtml(sourceName)}</span>` : "";
    const option = `<button type="button" id="document-option-${index}" class="document-option${index === state.activeResult ? " active" : ""}" data-path="${escapeHtml(entry.path)}" data-line="${entry.line || ""}" data-result="${index}" role="option" aria-selected="${index === state.activeResult}">
    <span class="document-title">${uiIcon(materialIcon(entry))}${kindBadgeHtml(entry)}${escapeHtml(entry.title || entry.stem)}${badge}${sourceBadge}</span>
    <span class="document-meta">${escapeHtml(tags)}</span>
    <span class="document-path-hint" title="${escapeHtml(entry.path)}">${escapeHtml(entry.path.split("/").slice(-2).join(" / "))}</span>
    ${snippet}
  </button>`;
    const worksheet = ["worksheet", "mini-worksheet"].includes(materialIcon(entry))
      || (!entry.solution && entry.path.endsWith("/ab.qmd"));
    if (!assignWorksheet || !worksheet || !entry.path.startsWith("unterricht/") || !entry.path.endsWith(".qmd")) return option;
    return `<div class="document-result-row" role="presentation">${option}
      <button type="button" class="document-assign" data-assign-result="${index}" aria-label="${escapeHtml(entry.title || entry.path)} zu Einheit hinzufügen">Zu Einheit hinzufügen</button>
    </div>`;
  }

  function readableSnippet(text) {
    return String(text).replace(/\\[a-zA-Z]+\{([^{}]*)\}/g, "$1")
      .replace(/\\[a-zA-Z]+/g, " ").replace(/[{}$#*|]/g, "")
      .replace(/\s+/g, " ").trim();
  }

  function kindBadgeHtml(entry) {
    if (materialIcon(entry) === "mini-worksheet") return '<span class="kind-badge">Mini-AB</span>';
    if (entry.kind !== "Kurs (H5P)") return "";
    return `<span class="kind-badge kind-badge--kurs">Kurs</span>`;
  }

  function documentSearchQuery() {
    if (search) return search.query("global");
    const current = state.qmds.find((entry) => entry.path === state.qmdPath);
    if (current && elements.documentSearch.value === documentLabel(current)) return "";
    return elements.documentSearch.value;
  }

  function documentLabel(entry) {
    return `${entry.title} · ${entry.path}`;
  }

  function filterMatches(entry) {
    const facets = state.facetFilters;
    if (facets.subject && entry.subject !== facets.subject) return false;
    if (facets.grade && entry.grade !== facets.grade) return false;
    if (facets.kind && entry.kind !== facets.kind) return false;
    if (facets.tag && !(entry.tags || []).some((tag) => tag === facets.tag || tag.startsWith(`${facets.tag}/`))) return false;
    if (facets.pdf === "with-pdf" && !entry.pdf) return false;
    if (facets.pdf === "without-pdf" && entry.pdf) return false;
    return true;
  }

  function compareDocumentMatches(a, b) {
    switch (state.facetFilters.sort) {
      case "recent":
        return b.entry.mtime - a.entry.mtime || b.score - a.score;
      case "title":
        return (a.entry.title || a.entry.stem).localeCompare(b.entry.title || b.entry.stem, "de") || b.score - a.score;
      default:
        return b.score - a.score || b.entry.mtime - a.entry.mtime;
    }
  }

  function scoreDocument(entry, parts) {
    if (!parts.length) return entry.area === "unterricht" ? 5 : 1;
    const haystack = normalizeSearch([entry.title, entry.path, entry.kind, entry.grade, entry.subject, (entry.tags || []).join(" ")].join(" "));
    if (!parts.every((part) => haystack.includes(part))) return -1;
    let score = 10;
    for (const part of parts) {
      if (normalizeSearch(entry.title || "").includes(part)) score += 80;
      if (normalizeSearch(entry.name || "").includes(part)) score += 40;
      if (normalizeSearch(entry.path || "").includes(part)) score += 2;
    }
    if (parts.every(part => normalizeSearch((entry.tags || []).join(" ")).includes(part))) score += 30;
    if (entry.area === "unterricht") score += 3;
    if (entry.kind === "Arbeitsblatt") score += 2;
    return score;
  }

  function openPicker() {
    renderFacetFilters();
    renderDocumentResults(false);
    elements.searchOverlay.hidden = false;
    elements.documentSearch.setAttribute("aria-expanded", "true");
  }

  function closePicker() {
    elements.searchOverlay.hidden = true;
    elements.documentSearch.setAttribute("aria-expanded", "false");
    elements.documentResults.removeAttribute("aria-activedescendant");
  }

  function handlePickerKeys(event) {
    const commandMode = commandQuery() !== null;
    const count = commandMode ? commandResults.length : state.filteredQmds.length;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openPicker();
      state.activeResult = Math.min(count - 1, state.activeResult + 1);
      renderDocumentResults(false);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      state.activeResult = Math.max(0, state.activeResult - 1);
      renderDocumentResults(false);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (commandMode) {
        const command = commandResults[state.activeResult];
        if (command) runCommand(command.id);
        return;
      }
      const entry = state.filteredQmds[state.activeResult];
      if (entry) openResult(entry);
    }
  }

  // Strg+K: Suche fokussieren und den Text markieren, ">" schaltet auf Befehle.
  function focusSearch() {
    elements.documentSearch.focus();
    elements.documentSearch.select();
  }

  // courseEntryForPath wandert in das kurse-Plugin (ctx.documents.registerPathResolver).

  let searchController = null;

  function searchKey() {
    return JSON.stringify([normalizeSearch(documentSearchQuery()).trim(), state.activeFilter, state.facetFilters]);
  }

  function showSearchStatus(message = "") {
    if (!elements.fulltextStatus) return;
    elements.fulltextStatus.textContent = message;
    elements.fulltextStatus.hidden = !message;
  }

  function scheduleFulltextSearch() {
    clearFulltextSearch();
    const query = documentSearchQuery();
    renderDocumentResults(false);
    if (query.trim().length < FULLTEXT_MIN_CHARS || commandQuery() !== null) return;
    const key = searchKey();
    const load = fulltext.load;
    fulltext.timer = setTimeout(async () => {
      fulltext.timer = null;
      const controller = new AbortController();
      searchController = controller;
      showSearchStatus("Volltextsuche läuft …");
      try {
        const params = new URLSearchParams({ q: query });
        for (const field of ["subject", "grade", "kind", "pdf", "sort"]) {
          if (state.facetFilters[field]) params.set(field, state.facetFilters[field]);
        }
        if (state.facetFilters.tag) params.set("tags", state.facetFilters.tag);
        const chip = state.activeFilter;
        if (chip === "unterricht") params.set("area", "unterricht");
        if (chip === "kurse") params.set("kind", "Kurs (H5P)");
        if (chip === "loesung") params.set("solution", "true");
        if (chip.startsWith("subject:") && !params.has("subject")) params.set("subject", chip.slice(8));
        if (chip.startsWith("kind:") && !params.has("kind")) params.set("kind", chip.slice(5));
        const data = await api(`/api/search?${params}`, { signal: controller.signal, timeout: 60000 });
        if (load !== fulltext.load || key !== searchKey()) return;
        fulltext.results = data.results || [];
        fulltext.sources = data.sources || [];
        const unavailable = (data.sourceErrors || []).map(error => error.name);
        showSearchStatus(unavailable.length ? `Suchquellen ausgefallen (${unavailable.join(", ")}).` : "");
        if (searchProviders) {
          // Lokale Plugin-Quellen (ctx.search.registerProvider) hinten anhaengen.
          const local = searchProviders.run(query, Object.fromEntries(params.entries()));
          fulltext.results = [...fulltext.results, ...local.results];
          fulltext.sources = [...fulltext.sources, ...searchProviders.sources()];
        }
        fulltext.key = key;
      } catch {
        if (load !== fulltext.load || key !== searchKey()) return;
        fulltext.results = [];
        showSearchStatus("Volltextsuche konnte nicht abgeschlossen werden.");
      } finally {
        if (searchController === controller) searchController = null;
      }
      renderDocumentResults(false);
    }, FULLTEXT_DEBOUNCE_MS);
  }

  function clearFulltextSearch() {
    if (fulltext.timer) clearTimeout(fulltext.timer);
    searchController?.abort();
    searchController = null;
    fulltext.timer = null;
    fulltext.load += 1;
    fulltext.results = [];
    fulltext.key = null;
    showSearchStatus();
  }

  return {
    renderFilterChips, renderFacetFilters, bindFacetChange, renderDocumentResults,
    documentSearchQuery, documentLabel, openPicker, closePicker, handlePickerKeys,
    scheduleFulltextSearch, clearFulltextSearch, registerCommands, focusSearch
  };
}
