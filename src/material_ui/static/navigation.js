import { materialIcon, normalizeSearch, pairMaterialEntries, materialDisplay } from "./ui-utils.js";

export function createNavigationController({ search, state, elements, views, api, escapeHtml, uiIcon, openModal, closeModal, setStatus, courseEntryForPath, fileActionButtons, refreshChatContext, folderMetadataChanged = () => {} }) {
  function navigationFolders() {
    const folders = new Set([""]);
    for (const entry of state.qmds) {
      const parts = entry.path.split("/");
      for (let depth = 1; depth < parts.length; depth += 1) folders.add(parts.slice(0, depth).join("/"));
    }
    return [...folders].sort((first, second) => first.localeCompare(second, "de", { numeric: true }));
  }

  // Die Kernansichten imitieren exakt die bisherigen Umschaltungen in
  // setNavigationView; der Rail-Zustand und der Wechselwächter liegen in der Registry.
  function activateFolderView() {
    elements.folderViewControls.hidden = false;
    elements.tagNavigation.hidden = true;
    elements.tagNavigationHint.hidden = true;
    elements.tagEntries.hidden = true;
    elements.folderEntries.hidden = false;
    elements.newDocInFolder.hidden = false;
    elements.folderNavHeading.textContent = "Ordner und Dateien";
    return renderFolderNavigation();
  }

  function activateTagTreeView() {
    elements.folderViewControls.hidden = true;
    elements.tagNavigation.hidden = false;
    elements.tagNavigationHint.hidden = false;
    elements.tagEntries.hidden = false;
    elements.folderEntries.hidden = true;
    elements.newDocInFolder.hidden = true;
    elements.folderNavHeading.textContent = "Material finden";
    state.navigationLoad += 1;
    const searchInput = document.getElementById("documentSearch");
    if (search) search.activate("tagTree");
    else searchInput.value = elements.tagSearch.value;
    searchInput.placeholder = "Material in dieser Auswahl suchen …";
    searchInput.setAttribute("aria-label", "Material in dieser Auswahl suchen");
    document.getElementById("searchOverlay").hidden = true;
    searchInput.setAttribute("aria-expanded", "false");
    renderTagNavigation();
  }

  function leaveTagTreeView() {
    const searchInput = document.getElementById("documentSearch");
    if (search) search.activate("global");
    else searchInput.value = "";
    searchInput.placeholder = "Material suchen: Thema, Klasse, Dateiname …";
    searchInput.setAttribute("aria-label", "Material suchen");
  }

  views?.registerView({ id: "folder", title: "Ordner", icon: "folder", order: 10, button: elements.folderViewButton, section: elements.folderNavigation, onActivate: activateFolderView });
  views?.registerView({ id: "tagTree", title: "Material finden", icon: "tag", order: 20, button: elements.tagTreeViewButton, section: elements.folderNavigation, onActivate: activateTagTreeView, onDeactivate: leaveTagTreeView });

  async function setNavigationView(view) {
    return views ? views.switchTo(view) : Promise.resolve(false);
  }

  function isTagDescendant(candidate, ancestor) {
    let cursor = candidate;
    const seen = new Set();
    while (state.tagParents[cursor] && !seen.has(cursor)) {
      seen.add(cursor);
      cursor = state.tagParents[cursor];
      if (cursor === ancestor) return true;
    }
    return false;
  }

  const YEAR_TAG_PATTERN = /^\d{2}\/\d{2}$/;

  function tagYearFilteredEntries() {
    return state.tagYearFilter
      ? state.qmds.filter((entry) => (entry.tags || []).includes(state.tagYearFilter))
      : state.qmds;
  }

  function tagYearOptions() {
    const years = new Set();
    for (const entry of state.qmds) {
      for (const tag of entry.tags || []) if (YEAR_TAG_PATTERN.test(tag)) years.add(tag);
    }
    return [...years].sort((first, second) => second.localeCompare(first, "de"));
  }

  function renderTagYearFilterOptions() {
    const years = tagYearOptions();
    if (state.tagYearFilter && !years.includes(state.tagYearFilter)) state.tagYearFilter = "";
    elements.tagYearFilter.innerHTML = '<option value="">Alle</option>'
      + years.map((year) => `<option value="${escapeHtml(year)}"${year === state.tagYearFilter ? " selected" : ""}>${escapeHtml(year)}</option>`).join("");
  }

  function categoryTags() {
    const tags = new Set(["arbeitsblatt", "aufgabenblatt", "foerdermaterial", "klausur", "klausuren", "loesung", "loesungen", "praesentation", "folien", "slide", "slides"]);
    for (const entry of state.qmds) {
      for (const value of [entry.subject, entry.grade, entry.kind]) if (value) tags.add(normalizeSearch(value));
    }
    return tags;
  }

  let categories = new Set();

  function isCategory(tag) {
    return YEAR_TAG_PATTERN.test(tag) || /^klasse[- _]?\d+/i.test(tag) || categories.has(normalizeSearch(tag));
  }

  function topicParent(tag) {
    let parent = state.tagParents[tag];
    const seen = new Set([tag]);
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      if (!isCategory(parent)) return parent;
      parent = state.tagParents[parent];
    }
    return "";
  }

  function scopedEntries() {
    return state.qmds.filter(entry => (selectedSubject === null || (entry.subject || "") === selectedSubject)
      && (selectedGrade === null || (entry.grade || "") === selectedGrade));
  }

  function filteredEntries() {
    const query = normalizeSearch((search?.query("tagTree") ?? elements.tagSearch.value).trim());
    const kind = elements.tagKindFilter.value;
    return tagYearFilteredEntries().filter(entry =>
      (selectedSubject === null || (entry.subject || "") === selectedSubject)
      && (selectedGrade === null || (entry.grade || "") === selectedGrade)
      && (!kind || (kind.startsWith("kind:") ? entry.kind === kind.slice(5) : materialIcon(entry) === kind))
      && [...selectedBadges].every(tag => (entry.tags || []).includes(tag))
      && (!query || normalizeSearch([entry.title, entry.stem, entry.path, ...(entry.tags || [])].join(" ")).includes(query)));
  }

  function buildTagTree() {
    const nodes = new Map();
    const ensure = tag => {
      if (!nodes.has(tag)) nodes.set(tag, { tag, children: new Map(), docs: new Set() });
      return nodes.get(tag);
    };
    const matchingPaths = new Set(filteredEntries().map(entry => entry.path));
    for (const entry of scopedEntries()) {
      for (const tag of entry.tags || []) {
        if (isCategory(tag)) continue;
        let cursor = tag;
        const seen = new Set();
        while (cursor && !seen.has(cursor)) {
          seen.add(cursor);
          const node = ensure(cursor);
          if (matchingPaths.has(entry.path)) node.docs.add(entry.path);
          cursor = topicParent(cursor);
        }
      }
    }
    const root = new Map();
    for (const node of nodes.values()) {
      const parent = topicParent(node.tag);
      if (parent && nodes.has(parent)) nodes.get(parent).children.set(node.tag, node);
      else root.set(node.tag, node);
    }
    return { root, nodes };
  }

  function sortTagNodes(nodes) {
    return nodes.sort((first, second) => second.docs.size - first.docs.size || first.tag.localeCompare(second.tag, "de"));
  }

  function sortTagDocs(entries) {
    return entries.sort((first, second) => (first.title || first.stem).localeCompare(second.title || second.stem, "de", { numeric: true }));
  }

  let selectedSubject = null;
  let selectedGrade = null;
  let selectedTag = "";
  const selectedBadges = new Set();
  let resultPage = 0;
  const pageSize = 20;
  let tagSearchTimer = null;
  const TAG_SEARCH_DEBOUNCE_MS = 300;

  function renderFacetOptions() {
    const kindValue = elements.tagKindFilter.value;
    const kinds = [...new Set(state.qmds.map(entry => entry.kind).filter(Boolean))].sort();
    elements.tagKindFilter.innerHTML = '<option value="">Alle Materialarten</option><option value="worksheet">Arbeitsblätter</option><option value="mini-worksheet">Mini-ABs</option><option value="solution">Lösungen</option><option value="slides">Folien</option><option value="note">Notizen</option><option value="file">Weitere</option>'
      + kinds.filter(kind => !["arbeitsblatt", "loesung", "praesentation", "deck", "notiz"].includes(normalizeSearch(kind))).map(kind => `<option value="kind:${escapeHtml(kind)}">${escapeHtml(kind)}</option>`).join("");
    elements.tagKindFilter.value = kindValue;
  }

  function renderTagNavigation() {
    for (const tag of selectedBadges) if (badgeExcluded(tag)) selectedBadges.delete(tag);
    categories = categoryTags();
    renderTagYearFilterOptions();
    renderFacetOptions();
    const { root, nodes } = buildTagTree();
    const path = [];
    let cursor = selectedTag;
    const seen = new Set();
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor);
      path.unshift(cursor);
      cursor = topicParent(cursor);
    }
    const subjectLabel = value => ({ mathematik: "Mathe", informatik: "Info" }[normalizeSearch(value)] || value || "Ohne Fach");
    const gradeLabel = value => value ? value.replace(/^klasse-/, "Klasse ") : "Ohne Klasse";
    const crumb = (stage, label, current = false) => `<button type="button" data-stage="${stage}"${current ? ' aria-current="location"' : ""}>${escapeHtml(label)}</button>`;
    let breadcrumbs = crumb("subjects", "Fächer", selectedSubject === null);
    if (selectedSubject !== null) breadcrumbs += '<span aria-hidden="true">›</span>' + crumb("grades", subjectLabel(selectedSubject), selectedGrade === null);
    if (selectedGrade !== null) breadcrumbs += '<span aria-hidden="true">›</span>' + crumb("topics", gradeLabel(selectedGrade), !selectedTag);
    breadcrumbs += path.map(tag => `<span aria-hidden="true">›</span><button type="button" data-topic="${escapeHtml(tag)}" data-tag="${escapeHtml(tag)}"${tag === selectedTag ? ' aria-current="location"' : ""}>${escapeHtml(tag)}</button>`).join("");
    elements.tagBreadcrumbs.innerHTML = breadcrumbs;
    elements.tagBack.hidden = selectedSubject === null;
    const level = selectedTag ? nodes.get(selectedTag)?.children : root;
    const choiceRow = (attribute, value, label) => `<li><button type="button" class="chip" ${attribute}="${escapeHtml(value)}"><span class="index-label">${escapeHtml(label)}</span><span aria-hidden="true">›</span></button></li>`;
    if (selectedSubject === null) {
      const subjects = [...new Set(state.qmds.map(entry => entry.subject || ""))].sort((a, b) => a.localeCompare(b, "de"));
      elements.tagTopicsHeading.textContent = "1 · Fach wählen";
      elements.tagEntries.innerHTML = subjects.map(value => choiceRow("data-subject", value, subjectLabel(value))).join("");
    } else if (selectedGrade === null) {
      const grades = [...new Set(state.qmds.filter(entry => (entry.subject || "") === selectedSubject).map(entry => entry.grade || ""))].sort((a, b) => a.localeCompare(b, "de", { numeric: true }));
      elements.tagTopicsHeading.textContent = "2 · Klasse wählen";
      elements.tagEntries.innerHTML = grades.map(value => choiceRow("data-grade", value, gradeLabel(value))).join("");
    } else {
      elements.tagTopicsHeading.textContent = selectedTag ? "Unterthemen" : "3 · Thema wählen";
      elements.tagEntries.innerHTML = level?.size
        ? sortTagNodes([...level.values()]).map(node => `<li><button type="button" class="chip" data-tag="${escapeHtml(node.tag)}"><span class="index-label">${escapeHtml(node.tag)}</span><span class="tag-count">${node.docs.size}</span><span aria-hidden="true">›</span></button></li>`).join("")
        : "";
    }
    elements.tagTopicsHeading.hidden = selectedGrade !== null && !level?.size;
    const showResults = Boolean(elements.tagSearch.value.trim()) || (selectedGrade !== null && (!!selectedTag || !root.size));
    elements.tagResults.hidden = !showResults;
    elements.tagResultsHeading.hidden = !showResults;
    elements.tagPagination.hidden = !showResults;
    elements.tagNavigationHint.hidden = selectedGrade === null;
    const filters = [elements.tagYearFilter, elements.tagKindFilter].filter(control => control.value);
    elements.tagActiveFilters.innerHTML = filters.map(control => `<button type="button" data-clear-filter="${control.id}" aria-label="${escapeHtml(control.selectedOptions[0].textContent)} entfernen">${escapeHtml(control.selectedOptions[0].textContent)} <span aria-hidden="true">×</span></button>`).join("");
    elements.tagReset.hidden = !filters.length && !elements.tagSearch.value && !selectedBadges.size;
    renderTagResults();
  }

  function indexLabelHtml(text) {
    return `<span class="index-label">${escapeHtml(text)}</span>`;
  }

  function badgeExcluded(tag) {
    const normalized = normalizeSearch(tag);
    const context = new Set([selectedSubject, selectedGrade, state.tagYearFilter].filter(Boolean).map(normalizeSearch));
    if (selectedSubject && ["mathematik", "mathe"].includes(normalizeSearch(selectedSubject))) { context.add("mathe"); context.add("mathematik"); }
    if (selectedSubject && ["informatik", "info"].includes(normalizeSearch(selectedSubject))) { context.add("info"); context.add("informatik"); }
    const kind = elements.tagKindFilter.value;
    const kindTags = { "mini-worksheet": ["mini-ab", "mini-arbeitsblatt", "arbeitsblatt"], worksheet: ["arbeitsblatt", "aufgabenblatt"], solution: ["loesung", "loesungen"], slides: ["praesentation", "folien", "slide", "slides"] };
    for (const value of kindTags[kind] || (kind.startsWith("kind:") ? [normalizeSearch(kind.slice(5))] : [])) context.add(value);
    let cursor = selectedTag;
    const seen = new Set();
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor);
      context.add(normalizeSearch(cursor));
      cursor = state.tagParents[cursor];
    }
    if (selectedGrade && /^klasse[- _]?0*\d+$/i.test(tag)) {
      const digits = value => value.match(/\d+/)?.[0].replace(/^0+/, "");
      if (digits(tag) === digits(selectedGrade)) return true;
    }
    return context.has(normalized);
  }

  function renderTagBadges(matches) {
    const counts = new Map();
    if (selectedGrade !== null && selectedTag) {
      for (const entry of matches) {
        for (const tag of new Set(entry.tags || [])) {
          if (!badgeExcluded(tag) && !selectedBadges.has(tag)) counts.set(tag, (counts.get(tag) || 0) + 1);
        }
      }
    }
    const badge = (tag, active, count) => `<button type="button" data-badge="${escapeHtml(tag)}" aria-pressed="${active}"${active ? ` aria-label="${escapeHtml(tag)} entfernen"` : ""}>${escapeHtml(tag)} <span class="tag-count">${active ? "×" : count}</span></button>`;
    elements.tagBadges.innerHTML = [...selectedBadges].map(tag => badge(tag, true)).join("")
      + [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "de")).map(([tag, count]) => badge(tag, false, count)).join("");
    elements.tagBadgePanel.hidden = !counts.size && !selectedBadges.size;
  }

  function renderTagResults() {
    const matches = sortTagDocs((selectedGrade === null && !elements.tagSearch.value.trim() ? [] : filteredEntries()).filter(entry =>
      !selectedTag || (entry.tags || []).some(tag => tag === selectedTag || isTagDescendant(tag, selectedTag))));
    renderTagBadges(matches);
    resultPage = Math.min(resultPage, Math.max(0, Math.ceil(matches.length / pageSize) - 1));
    elements.tagResultsHeading.textContent = `${selectedTag || "Alle Materialien"} · ${matches.length} Materialien`;
    elements.tagResults.innerHTML = matches.length
      ? matches.slice(resultPage * pageSize, (resultPage + 1) * pageSize).map(entry => `<li class="deck-entry"><button type="button" data-document="${escapeHtml(entry.path)}" title="${escapeHtml(entry.path)}" aria-current="${entry.path === state.qmdPath}">${uiIcon(materialIcon(entry))}${indexLabelHtml(entry.title || entry.stem)}</button></li>`).join("")
      : '<li class="muted">Keine Materialien gefunden. Filter anpassen oder zurücksetzen.</li>';
    elements.tagPageStatus.textContent = matches.length ? `${resultPage * pageSize + 1}–${Math.min(matches.length, (resultPage + 1) * pageSize)} von ${matches.length}` : "0 Treffer";
    elements.tagPrevious.disabled = resultPage === 0;
    elements.tagNext.disabled = (resultPage + 1) * pageSize >= matches.length;
  }

  function navigateTopic(tag) {
    selectedTag = tag;
    resultPage = 0;
    renderTagNavigation();
    (elements.tagBreadcrumbs.querySelector('[aria-current="location"]') || elements.tagBreadcrumbs.querySelector("button"))?.focus({ preventScroll: true });
  }
  function navigateStage(stage) {
    selectedTag = "";
    if (stage === "subjects") { selectedSubject = null; selectedGrade = null; }
    if (stage === "grades") selectedGrade = null;
    navigateTopic("");
  }
  elements.tagEntries.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.subject !== undefined) {
      selectedSubject = button.dataset.subject;
      selectedGrade = null;
      navigateTopic("");
    } else if (button.dataset.grade !== undefined) {
      selectedGrade = button.dataset.grade;
      navigateTopic("");
    } else if (button.dataset.tag !== undefined) navigateTopic(button.dataset.tag);
  });
  elements.tagBreadcrumbs.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (button?.dataset.stage) navigateStage(button.dataset.stage);
    else if (button?.dataset.topic !== undefined) navigateTopic(button.dataset.topic);
  });
  elements.tagBreadcrumbs.addEventListener("contextmenu", event => {
    const button = event.target.closest("[data-tag]");
    if (button) { event.preventDefault(); openTagRenameModal(button.dataset.tag); }
  });
  elements.tagBack.addEventListener("click", () => {
    if (selectedTag) navigateTopic(topicParent(selectedTag));
    else navigateStage(selectedGrade === null ? "subjects" : "grades");
  });
  elements.tagYearFilter.addEventListener("change", () => { resultPage = 0; });
  elements.tagKindFilter.addEventListener("change", () => { resultPage = 0; renderTagNavigation(); });
  elements.tagSearch.addEventListener("input", () => {
    search?.setQuery(elements.tagSearch.value, "tagTree");
    resultPage = 0;
    // Jede Tasteneingabe baut sonst sofort den kompletten Tag-Baum neu auf; beim Tippen
    // puffern wie die Volltextsuche im Picker (siehe FULLTEXT_DEBOUNCE_MS).
    if (tagSearchTimer) clearTimeout(tagSearchTimer);
    tagSearchTimer = setTimeout(() => { tagSearchTimer = null; renderTagNavigation(); }, TAG_SEARCH_DEBOUNCE_MS);
  });
  elements.tagActiveFilters.addEventListener("click", event => {
    const button = event.target.closest("[data-clear-filter]");
    if (!button) return;
    const control = [elements.tagYearFilter, elements.tagKindFilter].find(control => control.id === button.dataset.clearFilter);
    if (control) { control.value = ""; control.dispatchEvent(new Event("change")); }
    elements.tagFilterDetails.querySelector("summary").focus();
  });
  elements.tagReset.addEventListener("click", () => {
    selectedBadges.clear();
    resultPage = 0;
    for (const control of [elements.tagSearch, elements.tagKindFilter, elements.tagYearFilter]) control.value = "";
    if (search) search.setQuery("", "tagTree");
    else document.getElementById("documentSearch").value = "";
    elements.tagYearFilter.dispatchEvent(new Event("change"));
    document.getElementById("documentSearch").focus();
  });
  elements.tagBadges.addEventListener("click", event => {
    const button = event.target.closest("button[data-badge]");
    if (!button) return;
    const tag = button.dataset.badge;
    if (selectedBadges.has(tag)) selectedBadges.delete(tag);
    else selectedBadges.add(tag);
    resultPage = 0;
    renderTagNavigation();
    ([...elements.tagBadges.querySelectorAll("button")].find(button => button.dataset.badge === tag)
      || elements.tagBadges.querySelector("button") || document.getElementById("documentSearch")).focus({ preventScroll: true });
  });
  function changePage(delta) {
    resultPage += delta;
    renderTagResults();
    elements.tagResultsHeading.scrollIntoView({ block: "nearest" });
  }
  elements.tagPrevious.addEventListener("click", () => changePage(-1));
  elements.tagNext.addEventListener("click", () => changePage(1));

  let tagRenamePath = "";

  function allTagStrings() {
    const tags = new Set();
    for (const entry of state.qmds) for (const tag of entry.tags || []) tags.add(tag);
    for (const [child, parent] of Object.entries(state.tagParents)) {
      tags.add(child);
      tags.add(parent);
    }
    return tags;
  }

  function tagParentCandidates(tag) {
    return [...allTagStrings()]
      .filter((candidate) => candidate !== tag && !YEAR_TAG_PATTERN.test(candidate) && !isTagDescendant(candidate, tag))
      .sort((a, b) => a.localeCompare(b, "de"));
  }

  function openTagRenameModal(tag) {
    tagRenamePath = tag;
    elements.tagRenameSegment.value = tag;
    elements.tagRenameParent.value = state.tagParents[tag] || "";
    elements.tagRenameRoot.checked = state.rootTags.includes(tag);
    elements.tagRenameParentOptions.innerHTML = tagParentCandidates(tag)
      .map((candidate) => `<option value="${escapeHtml(candidate)}"></option>`).join("");
    elements.tagRenameStatus.textContent = `Aktueller Tag: ${tag}`;
    openModal(elements.tagRenameModal, elements.tagRenameSegment);
  }

  function closeTagRenameModal() {
    closeModal(elements.tagRenameModal);
  }

  async function applyTagRename() {
    const name = elements.tagRenameSegment.value.trim();
    if (!name) {
      elements.tagRenameStatus.textContent = "Bitte einen Namen angeben.";
      return;
    }
    const parent = elements.tagRenameParent.value.trim();
    elements.applyTagRename.disabled = true;
    try {
      let changed = [];
      if (name !== tagRenamePath) {
        const renameData = await api("/api/tags/rename", { method: "POST", body: JSON.stringify({ from: tagRenamePath, to: name }) });
        changed = renameData.changed || [];
      }
      await api("/api/tags/parent", { method: "POST", body: JSON.stringify({ tag: name, parent: parent || null }) });
      const data = await api("/api/tags/root", { method: "POST", body: JSON.stringify({ tag: name, root: elements.tagRenameRoot.checked }) });
      if (selectedTag === tagRenamePath) selectedTag = name;
      if (selectedBadges.delete(tagRenamePath)) selectedBadges.add(name);
      state.qmds = data.qmds || state.qmds;
      state.rootTags = data.rootTags || state.rootTags;
      state.tagParents = data.tagParents || state.tagParents;
      renderTagNavigation();
      closeTagRenameModal();
      elements.tagBreadcrumbs.querySelector('[aria-current="location"]')?.focus({ preventScroll: true });
      setStatus(changed.length ? `Tag umbenannt: ${changed.length} Dokument(e) aktualisiert.` : "Tag aktualisiert.", "ok");
    } catch (error) {
      elements.tagRenameStatus.textContent = `Speichern fehlgeschlagen: ${error.message}`;
    } finally {
      elements.applyTagRename.disabled = false;
    }
  }

  function navigateFolderInput() {
    const query = elements.navigationFolder.value.trim().replace(/^\/+|\/+$/g, "");
    const matches = navigationFolders().filter((folder) => folder === query || folder.endsWith(`/${query}`) || folder.endsWith(query));
    if (matches.length <= 1 || matches.includes(query)) {
      renderFolderNavigation(matches.includes(query) || !matches.length ? query : matches[0]);
    } else {
      state.navigationLoad += 1;
      state.folderTreeLoaded = false;
      elements.folderEntries.innerHTML = matches.length
        ? matches.map((folder) => `<li><button type="button" title="${escapeHtml(folder)}" data-folder="${escapeHtml(folder)}">${uiIcon("folder")}${indexLabelHtml(folder)}</button></li>`).join("")
        : '<li class="muted">Kein passender Ordner gefunden.</li>';
    }
  }

  // Repo-Wurzel mischt Unterrichtsmaterial mit Projekt-/Tool-Dateien (src, build, pyproject.toml, …);
  // Neueinsteiger:innen sehen auf Anhieb nur die Materialordner, der Rest bleibt eingeklappt erreichbar.
  const ROOT_CONTENT_FOLDERS = new Set(["unterricht", "foerdermaterial", "foerderempfehlungen", "wissen", "ressourcen"]);

  function folderLevelHtml(entries, { isRoot = false } = {}) {
    if (isRoot) {
      const content = entries.filter((entry) => ROOT_CONTENT_FOLDERS.has(entry.name));
      const other = entries.filter((entry) => !ROOT_CONTENT_FOLDERS.has(entry.name));
      if (other.length) {
        return (content.length ? renderFolderLevelEntries(content) : "")
          + `<li><details class="folder-project-group"><summary>Projektdateien</summary><ul class="index-list">${renderFolderLevelEntries(other)}</ul></details></li>`;
      }
    }
    return renderFolderLevelEntries(entries);
  }

  function renderFolderLevelEntries(entries) {
    const sorted = entries.slice().sort((first, second) => Number(second.directory) - Number(first.directory)
      || first.name.localeCompare(second.name, "de", { numeric: true }));
    const documents = new Map(state.qmds.map(entry => [entry.path, entry]));
    const enriched = sorted.map(entry => entry.directory ? entry : { ...entry, ...documents.get(entry.path) });
    return pairMaterialEntries(enriched).map(({ entry, solutions, notes }) => {
      if (entry.directory) {
        const courseEntry = state.qmds.find((item) => item.kind === "Kurs (H5P)" && item.path === entry.path);
        if (courseEntry) {
          return `<li class="deck-entry"><button type="button" data-document="${escapeHtml(courseEntry.path)}" title="${escapeHtml(entry.name)}" aria-current="${courseEntry.path === state.qmdPath}">${uiIcon("folder")}${indexLabelHtml(courseEntry.title || entry.name)}</button></li>`;
        }
        const newButton = `<button type="button" class="icon-button" data-new-in-folder="${escapeHtml(entry.path)}" title="Neue Datei in ${escapeHtml(entry.name)} anlegen" aria-label="Neue Datei in ${escapeHtml(entry.name)} anlegen">${uiIcon("plus")}</button>`;
        const unitButton = entry.path.startsWith('unterricht/') && /(?:^|\/)klasse-\d+(?:\/|$)/.test(entry.path)
          ? `<button type="button" class="folder-unit-action" data-unit-folder="${escapeHtml(entry.path)}" title="Als Lerneinheit einbinden" aria-label="Ordner ${escapeHtml(entry.name)} als Lerneinheit einbinden">${uiIcon("history")} Als Lerneinheit einbinden</button>` : '';
        const renameButton = `<button type="button" class="icon-button" data-rename-folder="${escapeHtml(entry.path)}" title="Ordner bearbeiten" aria-label="Ordner ${escapeHtml(entry.name)} bearbeiten">${uiIcon("rename")}</button>`;
        return `<li><details data-folder="${escapeHtml(entry.path)}"><summary draggable="${/^\d+_/.test(entry.name)}" data-folder="${escapeHtml(entry.path)}" title="${escapeHtml(entry.name)}">${uiIcon("folder")}${indexLabelHtml(entry.name)}${newButton}${renameButton}</summary>${unitButton}<ul class="index-list"></ul></details></li>`;
      }
      const document = state.qmds.find((item) => item.path === entry.path) || courseEntryForPath(entry.path);
      const actions = fileActionButtons(entry);
      if (entry.path.endsWith(".qmd") || document?.kind === "Kurs (H5P)") {
        // Gepaarte Dateien (Loesungen, AB-Notizen) zeigen statt Titel ein Kurzlabel.
        const materialFile = (file, pairedLabel = null) => {
          const { type, kind, title } = materialDisplay(file);
          const deckButton = file.deck
            ? `<button type="button" class="icon-button" data-present="${escapeHtml(file.deck)}" title="Verknüpftes Deck präsentieren">${uiIcon("play")}</button>`
            : "";
          const noteButton = !pairedLabel && !notes.length && ["worksheet", "mini-worksheet"].includes(type)
            ? `<button type="button" class="folder-note-create" data-worksheet-note="${escapeHtml(file.path)}" title="Neue Notiz anlegen" aria-label="Neue Notiz zu ${escapeHtml(title)} anlegen">${uiIcon("plus")}<span>Neue Notiz anlegen</span></button>`
            : "";
          const label = pairedLabel
            ? `<span class="folder-paired-label">${pairedLabel}</span>`
            : `<span class="folder-material-text"><span class="folder-material-kind">${escapeHtml(kind)}</span><span class="folder-material-title">${escapeHtml(title)}</span></span>`;
          const pairedClass = pairedLabel === "Lösung" ? " folder-paired-solution" : pairedLabel ? " folder-paired-note" : "";
          const width = 24 * ((["solution", "note"].includes(type) ? 1 : 2) + (file.deck ? 1 : 0)) + (noteButton ? 130 : 0);
          return `<div class="folder-material-file${pairedClass}" style="--file-actions-width:${width}px"><button type="button" class="folder-material-open" data-document="${escapeHtml(file.path)}" title="${escapeHtml(kind + ": " + title + "\n" + file.path)}" aria-label="${escapeHtml(kind + ": " + title)}" aria-current="${file.path === state.qmdPath}">${uiIcon(type)}${label}</button><div class="folder-file-actions">${deckButton}${fileActionButtons(file)}${noteButton}</div></div>`;
        };
        return `<li class="folder-material-group">${materialFile({ ...entry, ...document })}${solutions.map(file => materialFile(file, "Lösung")).join("")}${notes.map(file => materialFile(file, "Notizen")).join("")}</li>`;
      }
      if (entry.name.toLowerCase().endsWith(".excalidraw")) {
        const url = `/present/?path=${encodeURIComponent(entry.path)}`;
        return `<li class="deck-entry"><a href="${url}" target="_blank" rel="noopener" title="${escapeHtml(entry.name)}">${uiIcon(materialIcon(entry))}${indexLabelHtml(entry.name)}</a><button type="button" class="icon-button" data-present="${escapeHtml(entry.path)}" title="Mit der Present-App präsentieren">${uiIcon("play")}</button>${actions}</li>`;
      }
      if (entry.name.toLowerCase().endsWith(".md")) {
        const deckSource = sorted.find((item) => !item.directory && item.path === `${entry.path.slice(0, -3)}.excalidraw`);
        const presentButton = deckSource
          ? `<button type="button" class="icon-button" data-present="${escapeHtml(deckSource.path)}" title="Mit der Present-App präsentieren">${uiIcon("play")}</button>`
          : "";
        return `<li class="deck-entry"><button type="button" data-document="${escapeHtml(entry.path)}" title="${escapeHtml(entry.name)} im Editor öffnen" aria-current="${entry.path === state.qmdPath}">${uiIcon(materialIcon(entry))}${indexLabelHtml(entry.name)}</button>${presentButton}${actions}</li>`;
      }
      const pdf = entry.name.toLowerCase().endsWith(".pdf");
      const url = `/api/${pdf ? "pdf" : "file"}?path=${encodeURIComponent(entry.path)}`;
      return `<li class="deck-entry"><a href="${url}"${pdf ? ' target="_blank" rel="noopener"' : ""} title="${escapeHtml(entry.name)}">${uiIcon(pdf ? "pdf" : "file")}${indexLabelHtml(entry.name)}</a>${actions}</li>`;
    }).join("") || '<li class="muted">Keine Dateien in diesem Ordner.</li>';
  }

  const folderRequests = new WeakMap();

  function replaceFolderContents(listElement, entries, notes) {
    // Keep existing subtrees, including their open state and loaded children.
    // Descendant (not direct-child) selector: the root listing nests tool-/projektinterne
    // Ordner unterhalb der eingeklappten "Projektdateien"-Gruppe eine Ebene tiefer.
    const branches = new Map([...listElement.querySelectorAll("li > details[data-folder]")]
      .map(details => [details.dataset.folder, details]));
    const replacement = document.createElement("ul");
    const isRoot = listElement === elements.folderEntries;
    replacement.innerHTML = (notes?.text ? `<li class="folder-notes"><details><summary>Ordnerhinweise</summary><pre style="white-space:pre-wrap;font:inherit">${escapeHtml(notes.text)}</pre></details></li>` : "") + folderLevelHtml(entries, { isRoot });
    for (const details of replacement.querySelectorAll("li > details[data-folder]")) {
      const previous = branches.get(details.dataset.folder);
      if (previous) details.replaceWith(previous);
    }
    listElement.replaceChildren(...replacement.childNodes);
    listElement.dataset.loaded = "true";
  }

  async function loadFolderChildren(path, listElement, { reportError = false } = {}) {
    if (folderRequests.has(listElement)) return folderRequests.get(listElement);
    const load = state.navigationLoad;
    const isCurrent = () => listElement.isConnected
      && (listElement !== elements.folderEntries || load === state.navigationLoad);
    const pending = (async () => {
      listElement.setAttribute("aria-busy", "true");
      try {
        const data = await api(`/api/folder?path=${encodeURIComponent(path)}&metadata=1`);
        // A global navigation rebuild supersedes requests for its old DOM.
        if (!isCurrent()) return;
        state.folderCache.set(path, data);
        if (data.qmds) {
          state.qmds = state.qmds.filter(entry => entry.folder !== (path || ".") || entry.kind === "Kurs (H5P)")
            .concat(data.qmds.filter(entry => entry.area !== "wissen"));
          folderMetadataChanged();
        }
        replaceFolderContents(listElement, data.entries, data.notes);
        if (data.warnings?.length) setStatus(data.warnings.map(item => `${item.path}: ${item.message}`).join("; "), "error");
        return data;
      } catch (error) {
        if (isCurrent()) {
          if (listElement.dataset.loaded !== "true") listElement.textContent = error.message;
          setStatus(`Ordner konnte nicht geladen werden: ${error.message}`, "error");
        }
        if (reportError) throw error;
      } finally {
        listElement.removeAttribute("aria-busy");
        folderRequests.delete(listElement);
      }
    })();
    folderRequests.set(listElement, pending);
    return pending;
  }

  async function reloadCurrentFolder() {
    const path = state.navigationFolder;
    if (state.navigationView !== "folder") await setNavigationView("folder");
    const details = [...elements.folderEntries.querySelectorAll("details[data-folder]")]
      .find(entry => entry.dataset.folder === path);
    const list = path ? details?.querySelector(":scope > ul") : elements.folderEntries;
    if (!list) throw new Error("Aktueller Ordner ist nicht sichtbar.");
    const scrollContainer = elements.folderEntries.closest(".index-content");
    const scrollTop = scrollContainer?.scrollTop;
    const data = await loadFolderChildren(path, list, { reportError: true });
    if (scrollContainer) scrollContainer.scrollTop = scrollTop;
    return data;
  }

  async function ensureFolderExpanded(path) {
    const details = [...elements.folderEntries.querySelectorAll("details[data-folder]")].find((entry) => entry.dataset.folder === path);
    if (!details) return;
    const list = details.querySelector(":scope > ul");
    if (details.open && list.dataset.loaded === "true") return;
    // Setting open also emits toggle; both callers share the pending request.
    details.open = true;
    await loadFolderChildren(path, list);
  }

  function syncActiveDocumentMarkers() {
    refreshChatContext();
    // aria-current steht in jeder Listen-HTML fest eingebacken (siehe folderLevelHtml etc.);
    // bereits geladene Ordner-/Tag-Listen werden aus Cache-Gruenden nicht neu gerendert
    // (loadFolderChildren: listElement.dataset.loaded), deshalb hier direkt im DOM nachziehen.
    for (const button of document.querySelectorAll("button[data-document]")) {
      button.setAttribute("aria-current", String(button.dataset.document === state.qmdPath));
    }
  }

  function selectFolderRow(path) {
    state.navigationFolder = path;
    elements.navigationFolder.value = path;
    for (const summary of elements.folderEntries.querySelectorAll("summary[data-folder]")) {
      const selected = summary.dataset.folder === path;
      summary.classList.toggle("tree-selected", selected);
      summary.parentElement.classList.toggle("folder-selected", selected);
      if (selected) summary.setAttribute("aria-current", "location");
      else summary.removeAttribute("aria-current");
    }
  }

  async function renderFolderNavigation(folder = state.navigationFolder) {
    const load = ++state.navigationLoad;
    elements.navigationFolder.value = folder;
    const folders = navigationFolders();
    elements.navigationFolders.innerHTML = folders.filter(Boolean).map((path) => `<option value="${escapeHtml(path)}"></option>`).join("");
    if (!state.folderTreeLoaded) {
      elements.folderEntries.innerHTML = '<li class="muted">Ordner wird geladen …</li>';
      let data = state.folderCache.get("");
      if (!data) {
        try {
          data = await api(`/api/folder?path=${encodeURIComponent("")}`);
        } catch (error) {
          if (load === state.navigationLoad) elements.folderEntries.innerHTML = `<li class="muted">${escapeHtml(error.message)}</li>`;
          return;
        }
        state.folderCache.set("", data);
      }
      if (load !== state.navigationLoad) return;
      replaceFolderContents(elements.folderEntries, data.entries, data.notes);
      state.folderTreeLoaded = true;
    }
    const parts = folder.split("/").filter(Boolean);
    let acc = "";
    for (const part of parts) {
      acc = acc ? `${acc}/${part}` : part;
      await ensureFolderExpanded(acc);
      if (load !== state.navigationLoad) return;
    }
    selectFolderRow(folder);
  }


  return { setNavigationView, renderTagNavigation, openTagRenameModal, closeTagRenameModal, applyTagRename, navigateFolderInput, loadFolderChildren, syncActiveDocumentMarkers, selectFolderRow, renderFolderNavigation, reloadCurrentFolder };
}
