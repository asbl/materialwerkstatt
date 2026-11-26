import { consumeSseStream } from "../../../static/sse.js";
import { collapseContext, lineDiff } from "./diff.js";
import { clearAllThreads, createThread, loadThreads, saveThreads, titleFor } from "./history.js";
import { renderMarkdown } from "./markdown.js";
import {
  actionsFor, filterSlash, formatCustomPrompts, isSensitivePath, operatorFor, parseCustomPrompts, retryPrompt,
} from "./quick-actions.js";
import { baseToolName, extractHits, isBuiltinTool, isInternalTool, isToolError, toolLabel, toolOutputText } from "./tool-results.js";

const MODEL_KEY = "material-ui:chat-model";
const EFFORT_KEY = "material-ui:chat-effort";
const WIDTH_KEY = "material-ui:chat-width";
const WIDTH_MIN = 280;
const WIDTH_MAX = 720;
const WIDTH_DEFAULT = 340;
const RESULT_PREVIEW_CHARS = 2000;
const PREVIEW_LINES = 25;
const MAX_ATTACHMENTS = 5;
const EDITABLE = /\.(qmd|md|tex)$/i;
const STALE_EDIT = /geändert|gewechselt|nicht eindeutig/i;

function csrfToken() {
  return document.querySelector('meta[name="material-token"]')?.content || "";
}

export function applyDocumentEdit(current, snapshot, edit) {
  if (!snapshot || current?.path !== snapshot.path || current.text !== snapshot.text) {
    throw new Error("Das Dokument wurde gewechselt oder geändert. Bitte eine neue Änderung anfordern.");
  }
  if (edit.path !== snapshot.path || typeof edit.old_text !== "string" || !edit.old_text || typeof edit.new_text !== "string") {
    throw new Error("Ungültiger Änderungsvorschlag für die aktuelle Datei.");
  }
  const selection = snapshot.selection;
  const scoped = Boolean(selection);
  const start = scoped ? selection.start : 0;
  const end = scoped ? selection.end : current.text.length;
  const section = current.text.slice(start, end);
  const index = section.indexOf(edit.old_text);
  if (index < 0 || section.indexOf(edit.old_text, index + 1) !== -1) {
    throw new Error("Der zu ersetzende Abschnitt ist nicht eindeutig vorhanden. Bitte neu anfordern.");
  }
  const offset = start + index;
  return { offset, text: current.text.slice(0, offset) + edit.new_text + current.text.slice(offset + edit.old_text.length) };
}

function readModelChoices() {
  try { return JSON.parse(localStorage.getItem(MODEL_KEY) || "{}") || {}; } catch { return {}; }
}

function writeModelChoice(providerId, model) {
  try { localStorage.setItem(MODEL_KEY, JSON.stringify({ ...readModelChoices(), [providerId]: model })); } catch { /* ohne Speicher weiter */ }
}

function readEffortChoices() {
  try { return JSON.parse(localStorage.getItem(EFFORT_KEY) || "{}") || {}; } catch { return {}; }
}

function writeEffortChoice(providerId, effort) {
  try { localStorage.setItem(EFFORT_KEY, JSON.stringify({ ...readEffortChoices(), [providerId]: effort })); } catch { /* ohne Speicher weiter */ }
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    area.remove();
    return ok;
  }
}

export function createChatPanelController({
  elements, api, getDocument = () => null, replaceText, openDocument = null, storage,
  confirmAction = (message) => window.confirm(message),
}) {
  // Weitere Elemente des Docks (ohne Registrierung im Kern) werden bei Bedarf direkt gesucht.
  const el = (name) => elements[name] || document.getElementById(name);

  let providers = [];
  let sessionId = null;
  let sessionProviderId = null;
  let sessionModel = "";
  let sessionEffort = "";
  let preferredProviderId = null;
  let activeTurn = null;
  let history = [];
  let threads = [];
  let activeId = null;
  let pendingEdits = [];
  let applyAllItem = null;
  let attachments = [];
  let customPrompts = [];
  let quickSignature = "";
  let suggestions = { items: [], index: 0, kind: "" };
  let historyCursor = null;
  let historyDraft = "";
  let searchTimer = null;
  let searchToken = 0;
  let promptsLoaded = false;
  const confirmedSensitive = new Set();
  const pendingCalls = [];
  const pendingNewDocs = [];

  // -- Chats (Threads) und Verlauf ------------------------------------------------------------

  const activeThread = () => threads.find((thread) => thread.id === activeId) || null;
  const currentPath = () => getDocument()?.path || "";

  function syncThread() {
    const thread = activeThread();
    if (!thread) return;
    thread.sessionId = sessionId;
    thread.providerId = sessionProviderId;
    thread.model = sessionModel;
    thread.effort = sessionEffort;
    thread.messages = history;
    thread.docPath = thread.docPath || currentPath();
    thread.updated = Date.now();
    thread.title = titleFor(thread);
  }

  function renderThreadSelect() {
    const select = el("chatThread");
    if (!select) return;
    const ordered = [...threads].sort((a, b) => b.updated - a.updated);
    select.replaceChildren(...ordered.map((thread) => {
      const option = document.createElement("option");
      option.value = thread.id;
      option.textContent = thread.title || titleFor(thread);
      return option;
    }));
    select.value = activeId;
    select.disabled = Boolean(activeTurn) || threads.length < 2;
  }

  function persist() {
    syncThread();
    saveThreads({ activeId, threads }, storage);
    renderThreadSelect();
  }

  function startThread() {
    const thread = createThread({ docPath: currentPath() });
    threads.push(thread);
    activeId = thread.id;
    loadThreadState(thread);
  }

  function loadThreadState(thread) {
    sessionId = thread.sessionId;
    sessionProviderId = thread.providerId;
    sessionModel = thread.model;
    sessionEffort = thread.effort || "";
    history = thread.messages;
    pendingEdits = [];
    applyAllItem = null;
    pendingCalls.length = 0;
    pendingNewDocs.length = 0;
    attachments = [];
    renderAttachments();
    elements.chatMessages.replaceChildren();
    const empty = el("chatEmpty");
    if (empty) empty.hidden = history.length > 0;
    for (const message of history) appendMessage(message.role, message.text);
    renderActionsRow();
    applyThreadSelection(thread);
  }

  function applyThreadSelection(thread) {
    if (!providers.length) { preferredProviderId = thread.providerId; return; }
    const usable = providers.find((entry) => entry.id === thread.providerId && entry.available && !entry.blocked);
    if (usable) elements.chatProvider.value = usable.id;
    renderModelOptions();
    renderEffortOptions();
    refreshContext();
  }

  function scrollDown() {
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  }

  function currentModel() {
    return elements.chatModel && !elements.chatModel.hidden ? elements.chatModel.value : "";
  }

  function currentEffort() {
    const select = el("chatEffort");
    return select && !select.hidden ? select.value : "";
  }

  function updateControls() {
    const stopping = Boolean(activeTurn?.cancelled);
    elements.chatSend.disabled = Boolean(activeTurn);
    elements.chatStop.disabled = !activeTurn || stopping;
    elements.chatStop.hidden = !activeTurn;
    elements.chatNew.disabled = false;
    elements.chatProvider.disabled = Boolean(activeTurn);
    if (elements.chatModel) elements.chatModel.disabled = Boolean(activeTurn);
    const effortSelect = el("chatEffort");
    if (effortSelect) effortSelect.disabled = Boolean(activeTurn);
    const del = el("chatDelete");
    if (del) del.disabled = stopping;
    for (const chip of document.querySelectorAll("#chatQuick .chat-chip")) chip.disabled = Boolean(activeTurn);
    renderThreadSelect();
  }

  function refreshContext() {
    const current = getDocument();
    const operator = operatorFor(elements.chatProvider.value);
    const hasSelection = current?.selection?.end > current?.selection?.start;
    const sensitive = current && isSensitivePath(current.path);
    elements.chatContext.textContent = [
      current ? current.path.split("/").pop() : "Wissenssuche",
      hasSelection && "Auswahl",
      operator,
      sensitive && "⚠ Klausurmaterial",
    ].filter(Boolean).join(" · ");
    elements.chatContext.title = current
      ? `${current.path} (einschließlich ungespeicherter Änderungen)${hasSelection ? ` · Nur markierter Abschnitt (${current.selection.end - current.selection.start} Zeichen)` : ""} · Daten gehen an ${operator}.${sensitive ? " Klausurmaterial: Rückfrage vor dem Senden." : ""}`
      : `Keine bearbeitbare Datei geöffnet, Wissenssuche verfügbar. Daten gehen an ${operator}.`;
    renderQuick();
  }

  // -- Nachrichten --------------------------------------------------------------------------

  function copyButton(getText) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-copy";
    button.textContent = "Kopieren";
    button.setAttribute("aria-label", "Antwort kopieren");
    button.addEventListener("click", async () => {
      const ok = await copyToClipboard(getText());
      button.textContent = ok ? "Kopiert" : "Nicht möglich";
      setTimeout(() => { button.textContent = "Kopieren"; }, 1500);
    });
    return button;
  }

  function appendMessage(role, text, getRaw = null) {
    const item = document.createElement("li");
    item.className = `chat-message chat-message-${role}`;
    if (role === "assistant") {
      const body = document.createElement("div");
      body.className = "chat-md";
      body.append(renderMarkdown(text));
      item.append(body, copyButton(getRaw || (() => text)));
    } else {
      item.textContent = text;
    }
    elements.chatMessages.append(item);
    const empty = el("chatEmpty");
    if (empty) empty.hidden = true;
    scrollDown();
    return item;
  }

  function appendRecordedMessage(role, text) {
    history.push({ role, text });
    persist();
    return appendMessage(role, text);
  }

  // Aktionen unter der letzten Antwort: neu erzeugen, Frage bearbeiten.
  function renderActionsRow() {
    elements.chatMessages.querySelector(".chat-message-actions")?.remove();
    const last = history[history.length - 1];
    if (!last || last.role !== "assistant" || activeTurn) return;
    const row = document.createElement("li");
    row.className = "chat-message chat-message-actions";
    const regenerate = document.createElement("button");
    regenerate.type = "button";
    regenerate.textContent = "Neu erzeugen";
    regenerate.addEventListener("click", () => {
      const question = [...history].reverse().find((message) => message.role === "user");
      if (question) sendMessage(`Bitte beantworte das noch einmal neu und anders formuliert. Die Frage war: ${question.text}`, { display: "Antwort neu erzeugen" });
    });
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "Frage bearbeiten";
    edit.addEventListener("click", () => {
      const question = [...history].reverse().find((message) => message.role === "user");
      if (!question) return;
      elements.chatInput.value = question.text;
      elements.chatInput.focus();
    });
    row.append(regenerate, edit);
    elements.chatMessages.append(row);
    scrollDown();
  }

  // -- Werkzeugaufrufe ------------------------------------------------------------------------

  function formatInput(input) {
    if (input == null) return "";
    return typeof input === "string" ? input : JSON.stringify(input, null, 2);
  }

  function appendToolCall(event) {
    const builtin = isBuiltinTool(event.tool);
    const item = document.createElement("li");
    item.className = `chat-message chat-tool${builtin ? " chat-tool-builtin" : ""}`;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.className = "chat-tool-label";
    label.textContent = toolLabel(event.tool);
    const status = document.createElement("span");
    status.className = "chat-tool-status";
    status.textContent = "läuft …";
    summary.append(label, " ", status);
    details.append(summary);
    const input = formatInput(event.tool_input);
    if (input) {
      const pre = document.createElement("pre");
      pre.textContent = input.length > RESULT_PREVIEW_CHARS ? `${input.slice(0, RESULT_PREVIEW_CHARS)} …` : input;
      details.append(pre);
    }
    item.append(details);
    elements.chatMessages.append(item);
    scrollDown();
    pendingCalls.push({ tool: baseToolName(event.tool), item, details, status });
  }

  function renderHits(item, hits) {
    const list = document.createElement("ul");
    list.className = "chat-hits";
    for (const hit of hits.slice(0, 10)) {
      const row = document.createElement("li");
      const target = hit.page ? `${hit.path} · S. ${hit.page}` : hit.path;
      const text = hit.title ? `${hit.title} (${target})` : target;
      if (hit.sourceUrl) {
        const link = document.createElement("a");
        link.className = "chat-hit-link";
        link.href = hit.sourceUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = text;
        row.append(link);
      } else if (hit.openable && openDocument) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chat-hit-link";
        button.textContent = text;
        button.addEventListener("click", () => Promise.resolve(openDocument(hit.path)).catch((error) => appendMessage("error", error.message)));
        row.append(button);
      } else {
        const name = document.createElement("span");
        name.className = "chat-hit-path";
        name.textContent = text;
        row.append(name);
      }
      if (hit.snippet) {
        const snippet = document.createElement("span");
        snippet.className = "chat-hit-snippet";
        snippet.textContent = hit.snippet;
        row.append(snippet);
      }
      list.append(row);
    }
    item.append(list);
  }

  function completeToolCall(event) {
    const name = baseToolName(event.tool);
    let index = pendingCalls.findIndex((entry) => entry.tool === name);
    if (index < 0) {
      // Ergebnis ohne vorherigen Aufruf (manche CLIs buendeln beides): Zeile nachtraeglich anlegen.
      appendToolCall({ tool: event.tool, tool_input: null });
      index = pendingCalls.length - 1;
    }
    const [record] = pendingCalls.splice(index, 1);
    const failed = isToolError(event);
    record.status.textContent = failed ? "fehlgeschlagen" : "erledigt";
    record.item.classList.toggle("chat-tool-error", failed);
    const text = toolOutputText(event.tool_output);
    if (text) {
      const pre = document.createElement("pre");
      pre.textContent = text.length > RESULT_PREVIEW_CHARS ? `${text.slice(0, RESULT_PREVIEW_CHARS)} …` : text;
      record.details.append(pre);
    }
    if (failed) record.details.open = true;
    else {
      const hits = extractHits(event.tool, event.tool_output);
      if (hits.length) renderHits(record.item, hits);
    }
    scrollDown();
  }

  // -- Befunde der Regelpruefung ----------------------------------------------------------------

  function renderFindings(card, findings) {
    card.querySelector(".chat-findings")?.remove();
    const box = document.createElement("div");
    box.className = "chat-findings";
    if (!findings.length) {
      box.textContent = "✓ Keine neuen Regelhinweise.";
      box.classList.add("chat-findings-ok");
    } else {
      const heading = document.createElement("strong");
      heading.textContent = `${findings.length} Regelhinweis${findings.length === 1 ? "" : "e"}:`;
      const list = document.createElement("ul");
      for (const finding of findings.slice(0, 5)) {
        const li = document.createElement("li");
        li.className = `chat-finding chat-finding-${finding.level}`;
        li.textContent = `${finding.title} (Zeile ${finding.line}): ${finding.detail}`;
        list.append(li);
      }
      if (findings.length > 5) {
        const more = document.createElement("li");
        more.textContent = `… und ${findings.length - 5} weitere`;
        list.append(more);
      }
      box.append(heading, list);
      if (findings.some((finding) => finding.level === "warning")) card.classList.add("chat-edit-warning");
    }
    card.querySelector(".chat-edit-buttons")?.before(box);
  }

  async function checkProposal(card, path, text, oldText) {
    if (!EDITABLE.test(path)) return;
    try {
      const data = await api("/api/chat/check", { method: "POST", body: JSON.stringify({ path, text, old_text: oldText }) });
      renderFindings(card, data.new || []);
    } catch { /* Pruefung ist eine Zusatzinformation: bei Fehlern still bleiben */ }
  }

  // -- Aenderungsvorschlaege ------------------------------------------------------------------

  function renderDiff(oldText, newText) {
    const pre = document.createElement("pre");
    pre.className = "chat-diff";
    pre.setAttribute("aria-label", "Änderung als Zeilenvergleich");
    for (const op of collapseContext(lineDiff(oldText, newText))) {
      const line = document.createElement("span");
      line.className = `chat-diff-line chat-diff-${op.type}`;
      if (op.type === "skip") line.textContent = `… ${op.count} unveränderte Zeilen`;
      else line.textContent = `${op.type === "add" ? "+" : op.type === "del" ? "−" : " "} ${op.text}`;
      pre.append(line);
    }
    return pre;
  }

  function refreshApplyAll() {
    const open = pendingEdits.filter((entry) => !entry.applied);
    if (open.length < 2) {
      applyAllItem?.remove();
      applyAllItem = null;
      return;
    }
    if (!applyAllItem) {
      applyAllItem = document.createElement("li");
      applyAllItem.className = "chat-message chat-apply-all";
      const button = document.createElement("button");
      button.type = "button";
      button.addEventListener("click", () => {
        for (const entry of pendingEdits.filter((candidate) => !candidate.applied)) entry.apply();
      });
      applyAllItem.append(button);
    }
    applyAllItem.firstElementChild.textContent = `Alle ${open.length} Änderungen übernehmen`;
    elements.chatMessages.append(applyAllItem); // immer ans Ende
    scrollDown();
  }

  function appendRetry(edit, message) {
    const item = appendMessage("error", message);
    item.classList.add("chat-retry");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Auf aktuellem Stand neu anfordern";
    button.addEventListener("click", () => {
      button.disabled = true;
      sendMessage(retryPrompt(edit), { display: "Änderung auf dem aktuellen Stand erneut anfordern" });
    });
    item.append(" ", button);
  }

  function appendEdit(edit, snapshot) {
    const item = appendMessage("tool", "Änderungsvorschlag");
    item.classList.add("chat-edit");
    if (typeof edit.old_text === "string" && typeof edit.new_text === "string") item.append(renderDiff(edit.old_text, edit.new_text));
    const buttons = document.createElement("div");
    buttons.className = "chat-edit-buttons";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Änderung übernehmen";
    const entry = { applied: false, apply: null };
    entry.apply = () => {
      try {
        const result = applyDocumentEdit(getDocument(), snapshot, edit);
        replaceText(result.offset, edit.old_text.length, edit.new_text);
        snapshot.text = result.text;
        if (snapshot.selection?.end > snapshot.selection?.start) {
          snapshot.selection.end += edit.new_text.length - edit.old_text.length;
        }
        entry.applied = true;
        button.disabled = true;
        button.textContent = "Übernommen · Strg+Z macht rückgängig";
      } catch (error) {
        if (STALE_EDIT.test(error.message)) appendRetry(edit, error.message);
        else appendMessage("error", error.message);
      }
      refreshApplyAll();
    };
    button.addEventListener("click", entry.apply);
    buttons.append(button);
    item.append(buttons);
    pendingEdits.push(entry);
    refreshApplyAll();
    try {
      const resulting = applyDocumentEdit({ path: snapshot.path, text: snapshot.text }, snapshot, edit).text;
      checkProposal(item, snapshot.path, resulting, snapshot.text);
    } catch { /* nicht anwendbar: die Fehlermeldung kommt beim Klick */ }
  }

  // -- Neue Dateien ------------------------------------------------------------------------------

  function appendNewDocument(input) {
    const path = String(input.path || "");
    const text = String(input.text || "");
    const item = appendMessage("tool", "Neue Datei vorgeschlagen");
    item.classList.add("chat-edit", "chat-newdoc");
    const name = document.createElement("strong");
    name.className = "chat-newdoc-path";
    name.textContent = path;
    const pre = document.createElement("pre");
    pre.className = "chat-diff";
    const lines = text.split("\n");
    pre.textContent = lines.slice(0, PREVIEW_LINES).join("\n") + (lines.length > PREVIEW_LINES ? `\n… ${lines.length - PREVIEW_LINES} weitere Zeilen` : "");
    const buttons = document.createElement("div");
    buttons.className = "chat-edit-buttons";
    const create = document.createElement("button");
    create.type = "button";
    create.textContent = "Datei anlegen";
    const entry = { item, create, failed: false };
    create.addEventListener("click", async () => {
      create.disabled = true;
      try {
        const data = await api("/api/chat/documents", { method: "POST", body: JSON.stringify({ path, text }) });
        create.textContent = "Angelegt";
        watchRender(item, data.render);
        if (openDocument) {
          const open = document.createElement("button");
          open.type = "button";
          open.textContent = "Öffnen";
          open.addEventListener("click", () => Promise.resolve(openDocument(data.path)).catch((error) => appendMessage("error", error.message)));
          buttons.append(open);
        }
      } catch (error) {
        create.disabled = false;
        appendMessage("error", error.message);
      }
    });
    buttons.append(create);
    item.append(name, pre, buttons);
    pendingNewDocs.push(entry);
    if (EDITABLE.test(path)) checkProposal(item, path, text, "");
  }

  // -- Render-Status nach dem Anlegen einer neuen Datei -------------------------------------------

  const RENDER_POLL_MS = 1500;
  const RENDER_POLL_MAX_MS = 5 * 60 * 1000;

  function watchRender(item, render) {
    if (!render) return;
    const status = document.createElement("p");
    status.className = "chat-render-status";
    item.append(status);
    if (!render.started || !render.job_id) {
      status.textContent = render.reason ? `Render nicht gestartet: ${render.reason}` : "Kein Render gestartet.";
      return;
    }
    status.textContent = "Render läuft …";
    const deadline = Date.now() + RENDER_POLL_MAX_MS;
    (async () => {
      while (Date.now() < deadline) {
        let job = null;
        try {
          job = await api(`/api/jobs/${encodeURIComponent(render.job_id)}`);
        } catch { /* Status bleibt stehen, nächster Versuch */ }
        if (job && job.running === false) {
          showRenderResult(status, item, job);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, RENDER_POLL_MS));
      }
      status.textContent = "Render läuft noch – aktueller Stand in der Auftragsübersicht.";
    })();
  }

  function showRenderResult(status, item, job) {
    if (job.ok) {
      status.textContent = "Render erfolgreich.";
      status.classList.add("chat-render-ok");
      if (job.pdf) {
        const link = document.createElement("a");
        link.className = "chat-render-pdf";
        link.href = `/api/pdf?path=${encodeURIComponent(job.pdf)}`;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "PDF öffnen";
        status.append(" ", link);
      }
      return;
    }
    status.textContent = `Render fehlgeschlagen: ${job.message || "unbekannter Fehler"}`;
    status.classList.add("chat-render-error");
    const log = String(job.detail?.log || "").trim();
    if (log) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Render-Protokoll (letzte Zeilen)";
      const pre = document.createElement("pre");
      pre.className = "chat-render-log";
      pre.textContent = log.split("\n").slice(-30).join("\n");
      details.append(summary, pre);
      item.append(details);
    }
  }

  function completeNewDocument(event) {
    const entry = pendingNewDocs.shift();
    if (!entry || !isToolError(event)) return;
    entry.failed = true;
    entry.create.disabled = true;
    entry.item.classList.add("chat-tool-error");
    const note = document.createElement("p");
    note.className = "chat-newdoc-error";
    note.textContent = toolOutputText(event.tool_output) || "Der Vorschlag wurde abgelehnt.";
    entry.item.append(note);
  }

  // -- Provider und Modelle -------------------------------------------------------------------

  function renderUsageHint() {
    const provider = providers.find((entry) => entry.id === elements.chatProvider.value);
    const hint = provider?.usage_hint;
        if (!hint) {
      elements.chatUsage.textContent = "";
      return;
    }
    if (hint.kind === "bar" && typeof hint.limit === "number" && hint.limit > 0) {
      const percent = Math.min(100, Math.round((hint.used / hint.limit) * 100));
      elements.chatUsage.textContent = `${hint.label || "Nutzung"}: ${percent}%`;
    } else {
      elements.chatUsage.textContent = hint.message || "";
    }
  }

  function renderModelOptions() {
    const select = elements.chatModel;
    if (!select) return;
    const provider = providers.find((entry) => entry.id === elements.chatProvider.value);
    const models = provider?.models || [];
    select.hidden = models.length === 0;
    const label = el("chatModelLabel");
    if (label) label.hidden = select.hidden;
    select.replaceChildren(...models.map((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.label || model.id;
      return option;
    }));
    const wanted = (sessionProviderId === provider?.id ? sessionModel : null) ?? readModelChoices()[provider?.id] ?? "";
    select.value = models.some((model) => model.id === wanted) ? wanted : (models[0]?.id ?? "");
  }

  function renderEffortOptions() {
    const select = el("chatEffort");
    if (!select) return;
    const provider = providers.find((entry) => entry.id === elements.chatProvider.value);
    const efforts = provider?.efforts || [];
    select.hidden = efforts.length === 0;
    const label = el("chatEffortLabel");
    if (label) label.hidden = select.hidden;
    select.replaceChildren(...efforts.map((effort) => {
      const option = document.createElement("option");
      option.value = effort.id;
      option.textContent = effort.label || effort.id;
      return option;
    }));
    const wanted = (sessionProviderId === provider?.id && sessionEffort) || readEffortChoices()[provider?.id] || provider?.default_effort || "";
    select.value = efforts.some((effort) => effort.id === wanted) ? wanted : (efforts[0]?.id ?? "");
  }

  function renderProviderOptions() {
    elements.chatProvider.replaceChildren(...providers.map((provider) => {
      const option = document.createElement("option");
      option.value = provider.id;
      const suffix = [!provider.available && "nicht verfügbar", provider.blocked && "gesperrt", provider.experimental && "experimentell"].filter(Boolean).join(", ");
      option.textContent = suffix ? `${provider.id} (${suffix})` : provider.id;
      option.disabled = !provider.available || Boolean(provider.blocked);
      if (provider.blocked) option.title = provider.blocked;
      return option;
    }));
    const usable = (entry) => entry.available && !entry.blocked;
    const wanted = preferredProviderId || elements.chatProvider.value;
    const current = providers.find((entry) => entry.id === wanted && usable(entry));
    const firstAvailable = current || providers.find(usable);
    if (firstAvailable) elements.chatProvider.value = firstAvailable.id;
    preferredProviderId = null;
    renderModelOptions();
    renderEffortOptions();
    renderUsageHint();
    refreshContext();
  }

  async function loadProviders() {
    const data = await api("/api/chat/providers");
    providers = data.providers || [];
    renderProviderOptions();
  }

  // -- Sitzung ------------------------------------------------------------------------------

  async function closeSession() {
    if (!sessionId) return;
    const id = sessionId;
    await api(`/api/chat/sessions/${id}`, { method: "DELETE" });
    sessionId = null;
    sessionProviderId = null;
    sessionModel = "";
    sessionEffort = "";
  }

  async function ensureSession() {
    const providerId = elements.chatProvider.value;
    const model = currentModel();
    const effort = currentEffort();
    if (sessionId && providerId === sessionProviderId && model === sessionModel && effort === sessionEffort) return sessionId;
    if (sessionId) {
      await closeSession();
      if (history.length) {
        appendMessage("note", "Anbieter, Denkaufwand oder Modell gewechselt: Es beginnt eine neue Sitzung. Der sichtbare Verlauf bleibt, ist dem Modell aber nicht bekannt.");
      }
    }
    const data = await api("/api/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ provider: providerId, ...(model ? { model } : {}), ...(effort ? { effort } : {}) })
    });
    sessionId = data.session_id;
    sessionProviderId = providerId;
    sessionModel = model;
    sessionEffort = effort;
    persist();
    return sessionId;
  }

  // -- Ereignisse -----------------------------------------------------------------------------

  function handleEvent(event, assistant, snapshot, turn) {
    if (event.type === "text") {
      if (!assistant.item) {
        assistant.entry = { role: "assistant", text: "" };
        history.push(assistant.entry);
        assistant.item = appendMessage("assistant", "", () => assistant.entry.text);
      }
      assistant.entry.text += event.text;
      assistant.item.querySelector(".chat-md").replaceChildren(renderMarkdown(assistant.entry.text));
      scrollDown();
    } else if (event.type === "tool_call") {
      assistant.item = null; // folgender Text beginnt unterhalb des Werkzeugaufrufs
      if (isInternalTool(event.tool)) return;
      if (event.tool?.endsWith("propose_document_edit")) appendEdit(event.tool_input || {}, snapshot);
      else if (event.tool?.endsWith("propose_new_document")) appendNewDocument(event.tool_input || {});
      else appendToolCall(event);
    } else if (event.type === "tool_result") {
      if (isInternalTool(event.tool) || event.tool?.endsWith("propose_document_edit")) return;
      if (event.tool?.endsWith("propose_new_document")) completeNewDocument(event);
      else completeToolCall(event);
    } else if (event.type === "error") {
      if (event.code === "session_unknown") turn.sessionLost = true;
      else appendMessage("error", event.message || "Unbekannter Fehler.");
    }
  }

  async function streamMessage(id, text, snapshot, turn, sentAttachments) {
    const response = await fetch(`/api/chat/sessions/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Material-Token": csrfToken() },
      signal: turn.controller.signal,
      body: JSON.stringify({ text, document: snapshot, ...(sentAttachments.length ? { attachments: sentAttachments } : {}) })
    });
    const assistant = { item: null, entry: null };
    await consumeSseStream(response, (event) => {
      if (!turn.cancelled) handleEvent(event, assistant, snapshot, turn);
    });
  }

  function confirmSensitive(snapshot, sentAttachments) {
    const paths = [snapshot?.path, ...sentAttachments].filter((path) => path && isSensitivePath(path));
    const unconfirmed = paths.filter((path) => !confirmedSensitive.has(`${activeId}:${path}`));
    if (!unconfirmed.length) return true;
    const operator = operatorFor(elements.chatProvider.value);
    if (!confirmAction(`${unconfirmed.join(", ")} liegt in einem Klausurordner. Der Inhalt wird an ${operator} gesendet. Fortfahren?`)) return false;
    for (const path of unconfirmed) confirmedSensitive.add(`${activeId}:${path}`);
    return true;
  }

  // `override`: vorgegebener Text (Schnellaktion, Wiederholung); `display`: Text der Nutzerblase.
  async function sendMessage(override = null, { display = null } = {}) {
    const typed = typeof override === "string" ? override : elements.chatInput.value;
    const text = typed.trim();
    if (!text || activeTurn) return;
    hideSuggestions();
    const snapshot = getDocument();
    const sentAttachments = [...attachments];
    if (!confirmSensitive(snapshot, sentAttachments)) return;
    let finish;
    const turn = { controller: new AbortController(), cancelled: false, sessionLost: false, finished: new Promise((resolve) => { finish = resolve; }) };
    activeTurn = turn;
    pendingEdits = [];
    applyAllItem = null;
    pendingCalls.length = 0;
    pendingNewDocs.length = 0;
    updateControls();
    renderActionsRow();
    appendRecordedMessage("user", display ?? text);
    historyCursor = null;
    if (typeof override !== "string") elements.chatInput.value = "";
    attachments = [];
    renderAttachments();
    refreshContext();
    try {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        turn.sessionLost = false;
        const id = await ensureSession();
        if (turn.cancelled) break;
        await streamMessage(id, text, snapshot, turn, sentAttachments);
        if (!turn.sessionLost || turn.cancelled) break;
        // Die Sitzung ist serverseitig abgelaufen (Leerlauf oder Neustart): einmal neu beginnen.
        sessionId = null;
        sessionProviderId = null;
        sessionModel = "";
        sessionEffort = "";
        if (attempt === 0) appendMessage("note", "Die Sitzung war abgelaufen. Es wurde eine neue gestartet; frühere Nachrichten kennt das Modell nicht mehr.");
      }
      if (turn.sessionLost && !turn.cancelled) appendMessage("error", "Die Chat-Sitzung ist nicht mehr verfügbar. Bitte „Neuer Chat“ wählen.");
    } catch (error) {
      if (!turn.cancelled) appendMessage("error", error.message || "Unbekannter Fehler.");
    } finally {
      activeTurn = null;
      finish();
      persist();
      updateControls();
      if (!turn.cancelled) {
        renderActionsRow();
        elements.chatInput.focus();
      }
    }
  }

  // Bricht nur die laufende Antwort ab: Sitzung, Kontext und Verlauf bleiben erhalten.
  async function stopResponse() {
    const turn = activeTurn;
    if (!turn || turn.cancelled) return;
    turn.cancelled = true;
    updateControls();
    if (sessionId) {
      try {
        await api(`/api/chat/sessions/${sessionId}/cancel`, { method: "POST" });
      } catch { /* der Abbruch der Verbindung unten beendet die Runde ebenfalls */ }
    }
    turn.controller.abort();
    await turn.finished;
    appendMessage("note", "Antwort abgebrochen. Der bisherige Verlauf bleibt erhalten; der abgebrochene Teil der Antwort ist dem Modell nicht bekannt.");
    renderActionsRow();
    elements.chatInput.focus();
  }

  // "Neuer Chat" legt einen weiteren Chat an; der bisherige bleibt in der Liste erhalten.
  async function newChat() {
    if (activeTurn) await stopResponse();
    syncThread();
    const thread = activeThread();
    if (thread && !thread.messages.length && !thread.sessionId) {
      elements.chatInput.value = "";
      elements.chatInput.focus();
      return;
    }
    startThread();
    elements.chatInput.value = "";
    persist();
    refreshContext();
    elements.chatInput.focus();
  }

  async function deleteChat() {
    if (activeTurn) await stopResponse();
    try {
      await closeSession();
    } catch (error) {
      appendMessage("error", `Sitzung konnte nicht beendet werden: ${error.message}`);
      return;
    }
    threads = threads.filter((thread) => thread.id !== activeId);
    const next = [...threads].sort((a, b) => b.updated - a.updated)[0];
    if (next) { activeId = next.id; loadThreadState(next); } else startThread();
    elements.chatInput.value = "";
    persist();
    refreshContext();
  }

  function switchThread(id) {
    if (activeTurn || id === activeId) return;
    const target = threads.find((thread) => thread.id === id);
    if (!target) return;
    syncThread();
    activeId = id;
    loadThreadState(target);
    persist();
    refreshContext();
  }

  // -- Schnellaktionen, eigene Prompts ------------------------------------------------------------

  function renderQuick() {
    const box = el("chatQuick");
    if (!box) return;
    const actions = actionsFor(currentPath(), customPrompts);
    const signature = `${currentPath()}|${actions.map((action) => action.title).join("|")}`;
    if (signature === quickSignature) return;
    quickSignature = signature;
    box.replaceChildren(...actions.map((action) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chat-chip";
      chip.textContent = action.title;
      chip.title = action.prompt;
      chip.disabled = Boolean(activeTurn);
      chip.addEventListener("click", () => sendMessage(action.prompt, { display: action.title }));
      return chip;
    }));
    box.hidden = actions.length === 0;
  }

  async function loadPrompts() {
    try {
      customPrompts = (await api("/api/chat/prompts")).prompts || [];
    } catch {
      customPrompts = [];
    }
    const area = el("chatPromptsText");
    if (area) area.value = formatCustomPrompts(customPrompts);
    quickSignature = "";
    renderQuick();
  }

  async function savePrompts() {
    const status = el("chatPromptsStatus");
    const { prompts, errors } = parseCustomPrompts(el("chatPromptsText").value);
    if (errors.length) {
      if (status) status.textContent = errors.join(" ");
      return;
    }
    try {
      customPrompts = (await api("/api/chat/prompts", { method: "PUT", body: JSON.stringify({ prompts }) })).prompts;
      if (status) status.textContent = `${customPrompts.length} Prompt${customPrompts.length === 1 ? "" : "s"} gespeichert.`;
      quickSignature = "";
      renderQuick();
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  }

  // -- Vorschlagsmenue (Slash-Befehle und @Dateien) ---------------------------------------------

  function hideSuggestions() {
    suggestions = { items: [], index: 0, kind: "" };
    const menu = el("chatSuggest");
    if (menu) { menu.hidden = true; menu.replaceChildren(); }
    elements.chatInput.removeAttribute("aria-activedescendant");
  }

  function renderSuggestions() {
    const menu = el("chatSuggest");
    if (!menu) return;
    if (!suggestions.items.length) { hideSuggestions(); return; }
    menu.hidden = false;
    menu.replaceChildren(...suggestions.items.map((item, index) => {
      const row = document.createElement("li");
      row.id = `chatSuggest-${index}`;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(index === suggestions.index));
      row.className = `chat-suggest-item${index === suggestions.index ? " active" : ""}`;
      const label = document.createElement("span");
      label.textContent = item.label;
      row.append(label);
      if (item.detail) {
        const detail = document.createElement("small");
        detail.textContent = item.detail;
        row.append(" ", detail);
      }
      row.addEventListener("mousedown", (event) => { event.preventDefault(); pickSuggestion(index); });
      return row;
    }));
    elements.chatInput.setAttribute("aria-activedescendant", `chatSuggest-${suggestions.index}`);
  }

  function pickSuggestion(index) {
    const item = suggestions.items[index];
    if (!item) return;
    hideSuggestions();
    item.onPick();
    elements.chatInput.focus();
  }

  async function updateSuggestions() {
    const value = elements.chatInput.value;
    const caret = elements.chatInput.selectionStart ?? value.length;
    if (value.startsWith("/") && !value.includes("\n")) {
      const actions = filterSlash(value, actionsFor(currentPath(), customPrompts));
      suggestions = {
        kind: "slash", index: 0,
        items: actions.map((action) => ({
          label: action.title, detail: action.custom ? "eigener Prompt" : "",
          onPick: () => { elements.chatInput.value = action.prompt; },
        })),
      };
      renderSuggestions();
      return;
    }
    const mention = /(^|\s)@([^\s@]*)$/.exec(value.slice(0, caret));
    if (mention && attachments.length < MAX_ATTACHMENTS) {
      const query = mention[2];
      clearTimeout(searchTimer);
      const token = ++searchToken;
      if (!query) { hideSuggestions(); return; }
      searchTimer = setTimeout(async () => {
        try {
          const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
          if (token !== searchToken) return;
          const items = (data.results || [])
            .filter((result) => /^(unterricht|wissen)\//.test(result.path) && /\.(qmd|md|tex|yaml|csv)$/i.test(result.path))
            .filter((result) => !attachments.includes(result.path))
            .slice(0, 6)
            .map((result) => ({
              label: result.title || result.path, detail: result.path,
              onPick: () => {
                attachments.push(result.path);
                elements.chatInput.value = elements.chatInput.value.replace(/(^|\s)@[^\s@]*$/, "$1");
                renderAttachments();
              },
            }));
          suggestions = { kind: "mention", index: 0, items };
          renderSuggestions();
        } catch { hideSuggestions(); }
      }, 200);
      return;
    }
    searchToken += 1;
    hideSuggestions();
  }

  function renderAttachments() {
    const box = el("chatAttachments");
    if (!box) return;
    box.hidden = attachments.length === 0;
    box.replaceChildren(...attachments.map((path) => {
      const chip = document.createElement("span");
      chip.className = "chat-attachment";
      chip.textContent = `📎 ${path.split("/").pop()}`;
      chip.title = path;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Anhang ${path} entfernen`);
      remove.textContent = "✕";
      remove.addEventListener("click", () => { attachments = attachments.filter((item) => item !== path); renderAttachments(); });
      chip.append(" ", remove);
      return chip;
    }));
  }

  // -- Eingabe ------------------------------------------------------------------------------------

  function userMessages() {
    return history.filter((message) => message.role === "user").map((message) => message.text);
  }

  function handleInputKeydown(event) {
    if (suggestions.items.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const count = suggestions.items.length;
        suggestions.index = (suggestions.index + (event.key === "ArrowDown" ? 1 : count - 1)) % count;
        renderSuggestions();
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        pickSuggestion(suggestions.index);
        return;
      }
      if (event.key === "Escape") {
        // Nur das Menue schliessen; Escape soll nicht zusaetzlich den Chat oder Fokusmodus beenden.
        event.preventDefault();
        event.stopPropagation();
        hideSuggestions();
        return;
      }
    }
    if (event.key === "ArrowUp" && !event.shiftKey && elements.chatInput.selectionStart === 0 && elements.chatInput.selectionEnd === 0) {
      const messages = userMessages();
      if (!messages.length) return;
      event.preventDefault();
      if (historyCursor === null) { historyDraft = elements.chatInput.value; historyCursor = messages.length; }
      historyCursor = Math.max(0, historyCursor - 1);
      elements.chatInput.value = messages[historyCursor];
      elements.chatInput.setSelectionRange(0, 0);
      return;
    }
    if (event.key === "ArrowDown" && historyCursor !== null && elements.chatInput.selectionStart === elements.chatInput.value.length) {
      event.preventDefault();
      const messages = userMessages();
      historyCursor += 1;
      if (historyCursor >= messages.length) { historyCursor = null; elements.chatInput.value = historyDraft; } else elements.chatInput.value = messages[historyCursor];
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  function handleInput() {
    historyCursor = null;
    updateSuggestions();
  }

  // -- Breite -------------------------------------------------------------------------------------

  function applyChatWidth(width) {
    const clamped = Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, Math.round(width)));
    const workspace = document.getElementById("workspace");
    if (workspace) workspace.style.setProperty("--chat-width", `${clamped}px`);
    const handle = el("chatResizer");
    if (handle) {
      handle.setAttribute("aria-valuemin", String(WIDTH_MIN));
      handle.setAttribute("aria-valuemax", String(WIDTH_MAX));
      handle.setAttribute("aria-valuenow", String(clamped));
    }
    return clamped;
  }

  function persistWidth(width) {
    try { localStorage.setItem(WIDTH_KEY, String(width)); } catch { /* ohne Speicher weiter */ }
  }

  function bindResizer() {
    const handle = el("chatResizer");
    if (!handle) return;
    let width = WIDTH_DEFAULT;
    try {
      const saved = Number(localStorage.getItem(WIDTH_KEY));
      if (Number.isFinite(saved) && saved >= WIDTH_MIN && saved <= WIDTH_MAX) width = saved;
    } catch { /* Standardbreite */ }
    width = applyChatWidth(width);
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = el("chatDock").getBoundingClientRect().width || width;
      handle.setPointerCapture?.(event.pointerId);
      const move = (moveEvent) => { width = applyChatWidth(startWidth + startX - moveEvent.clientX); };
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        persistWidth(width);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
    handle.addEventListener("keydown", (event) => {
      const step = event.shiftKey ? 80 : 24;
      if (event.key === "ArrowLeft") width = applyChatWidth(width + step);
      else if (event.key === "ArrowRight") width = applyChatWidth(width - step);
      else if (event.key === "Home") width = applyChatWidth(WIDTH_DEFAULT);
      else return;
      event.preventDefault();
      persistWidth(width);
    });
    handle.addEventListener("dblclick", () => { width = applyChatWidth(WIDTH_DEFAULT); persistWidth(width); });
  }

  // -- Start ----------------------------------------------------------------------------------------

  async function ensureProvidersLoaded() {
    refreshContext();
    if (!providers.length) {
      try {
        await loadProviders();
      } catch (error) {
        appendMessage("error", error.message);
      }
    }
    if (!promptsLoaded) {
      promptsLoaded = true;
      loadPrompts();
    }
  }

  function handleProviderChange() {
    renderModelOptions();
    renderEffortOptions();
    renderUsageHint();
    refreshContext();
  }

  function handleEffortChange() {
    const select = el("chatEffort");
    if (select) writeEffortChoice(elements.chatProvider.value, select.value);
  }

  function handleModelChange() {
    if (elements.chatModel) writeModelChoice(elements.chatProvider.value, elements.chatModel.value);
  }

  // Verlauf und Sitzung nach einem Neuladen wiederherstellen (Sitzung lebt serverseitig weiter,
  // bis sie ablaeuft; dann startet sendMessage automatisch eine neue).
  function restoreHistory() {
    const saved = loadThreads(storage);
    threads = saved.threads;
    activeId = saved.activeId;
    if (!threads.length) { startThread(); return; }
    const thread = activeThread();
    loadThreadState(thread);
    preferredProviderId = thread.providerId;
    if (history.length) appendMessage("note", "Verlauf wiederhergestellt.");
  }

  function bindExtras() {
    el("chatInput")?.addEventListener("input", handleInput);
    el("chatEffort")?.addEventListener("change", handleEffortChange);
    el("chatInput")?.addEventListener("blur", () => setTimeout(hideSuggestions, 120));
    el("chatThread")?.addEventListener("change", (event) => switchThread(event.target.value));
    el("chatDelete")?.addEventListener("click", deleteChat);
    el("chatPromptsSave")?.addEventListener("click", savePrompts);
    bindResizer();
  }

  restoreHistory();
  bindExtras();
  renderThreadSelect();
  updateControls();

  return {
    refreshContext, stopResponse, newChat, deleteChat, ensureProvidersLoaded, sendMessage, loadProviders,
    handleProviderChange, handleModelChange, handleInputKeydown, clearAll: () => clearAllThreads(storage),
  };
}
