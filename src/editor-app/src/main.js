// CodeMirror-6-Editor fuer die Material-UI. Wird per Vite als
// `static/editor.bundle.js` gebaut (IIFE, global `MaterialEditor`) und von
// `static/editor.js` als Adapter angebunden. Die Bedienoberflaeche
// (Bausteine, Statustext, Speichern/Rendern) bleibt in den ungebauten
// Modulen; dieser Bundle erhält sie als Optionen.
import { EditorView, Decoration, ViewPlugin, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { EditorState, Compartment, StateEffect, StateField, Prec } from "@codemirror/state";
import { history, defaultKeymap, historyKeymap, indentMore, indentLess } from "@codemirror/commands";
import { search, searchKeymap, openSearchPanel } from "@codemirror/search";
import { codeFolding, foldGutter, foldService, foldEffect, unfoldEffect, foldedRanges, foldable, bracketMatching, indentUnit } from "@codemirror/language";
import { autocompletion, closeBrackets, closeCompletion } from "@codemirror/autocomplete";
import { diagnosticsEffect, diagnosticsField } from "./diagnostics.js";

const AUTOCOMPLETE_TRIGGER = /\[([A-Za-zÄÖÜäöü][A-Za-z0-9-]*)$/;
const AUTOCOMPLETE_LIMIT = 8;
const FLASH_MS = 1800;

const flashEffect = StateEffect.define();

const flashField = StateField.define({
  create: () => Decoration.none,
  update: (value, transaction) => {
    value = value.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (effect.is(flashEffect)) value = effect.value === null ? Decoration.none : effect.value;
    }
    return value;
  },
  provide: field => EditorView.decorations.from(field)
});

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isCommandLine(line) {
  return /^\s*(\\[A-Za-z@]+|:::+|!!!|@\w[\w-]*|#\|)/.test(line);
}

// Faltbare Kommandobloecke: ::: umgebungen, \begin/\end-Umgebungen und
// aufeinanderfolgende #|-Zeilen. Portiert aus dem bisherigen Overlay-Editor.
function foldableCommandBlock(lines, start) {
  const line = lines[start] || "";
  const trimmed = line.trim();
  // YAML-Frontmatter am Dokumentanfang: Metadaten, Template und Header-Includes.
  if (start === 0 && /^---\s*$/.test(trimmed)) return fencedCommandBlock(lines, start, /^(---|\.\.\.)\s*$/);
  if (/^:::\s*\{/.test(trimmed)) return fencedCommandBlock(lines, start, /^:::\s*$/);
  const env = trimmed.match(/^\\begin\{([^}]+)\}/);
  if (env) return fencedCommandBlock(lines, start, new RegExp(`^\\\\end\\{${escapeRegExp(env[1])}\\}`));
  if (/^#\|/.test(trimmed)) return consecutiveCommandLines(lines, start);
  return null;
}

function fencedCommandBlock(lines, start, closePattern) {
  for (let index = start + 1; index < lines.length; index += 1) {
    if (closePattern.test(lines[index].trim()) && index - start >= 2) return { end: index };
  }
  return null;
}

function consecutiveCommandLines(lines, start) {
  let end = start;
  while (end + 1 < lines.length && /^#\|/.test(lines[end + 1].trim())) end += 1;
  return end - start >= 2 ? { end } : null;
}

const FRONTMATTER_AUTOFOLD_MIN_LINES = 5;

function docLines(state) {
  const lines = [];
  for (let position = 1; position <= state.doc.lines; position += 1) lines.push(state.doc.line(position).text);
  return lines;
}

function commandBlockRanges(state) {
  const lines = docLines(state);
  const ranges = [];
  for (let index = 0; index < lines.length; index += 1) {
    // Spaltenlayouts beim Öffnen sichtbar lassen; manuelles Falten bleibt möglich.
    if (/^\s*:::\s*\{[^}]*\.(?:spalten|spalte|columns|column)(?=[\s}])/.test(lines[index])) continue;
    const block = foldableCommandBlock(lines, index);
    if (!block) continue;
    // Kurzes Frontmatter (nur Titel o. ae.) bleibt beim Oeffnen sichtbar.
    if (index === 0 && /^---\s*$/.test(lines[0].trim()) && block.end - index < FRONTMATTER_AUTOFOLD_MIN_LINES) continue;
    const from = state.doc.line(index + 1).from;
    const to = state.doc.line(block.end + 1).to;
    ranges.push({ from, to, index, end: block.end });
    index = block.end;
  }
  return ranges;
}

function foldAllCommandBlocks(view) {
  const ranges = commandBlockRanges(view.state);
  if (!ranges.length) return;
  view.dispatch({
    effects: ranges.map((range) => foldEffect.of(range))
  });
}

function unfoldAround(view, from, to) {
  const effects = [];
  foldedRanges(view.state).between(from, to, (rangeFrom, rangeTo) => {
    if (rangeTo >= from && rangeFrom <= to) effects.push(unfoldEffect.of({ from: rangeFrom, to: rangeTo }));
  });
  if (effects.length) view.dispatch({ effects });
}

function foldedRangeAt(state, position) {
  let found = null;
  foldedRanges(state).between(0, state.doc.length, (from, to) => {
    if (from <= position && position <= to) found = { from, to };
  });
  return found;
}

function foldPlaceholderData(state, range) {
  const firstLine = state.doc.lineAt(range.from);
  const lastLine = state.doc.lineAt(range.to);
  let label = firstLine.text.trim().replace(/\s+/g, " ").slice(0, 72);
  if (firstLine.number === 1 && /^---\s*$/.test(firstLine.text)) {
    // Frontmatter: den Titel nennen statt der nichtssagenden Trennzeile.
    let title = "";
    for (let number = 2; number <= lastLine.number; number += 1) {
      const match = state.doc.line(number).text.match(/^title:\s*["']?(.*?)["']?\s*$/);
      if (match) { title = match[1]; break; }
    }
    label = `Metadaten${title ? ` · ${title}` : ""}`.slice(0, 72);
  }
  return { count: lastLine.number - firstLine.number + 1, label };
}

function foldPlaceholderDOM(view, onclick, prepared) {
  const span = document.createElement("span");
  span.className = "qmd-fold-placeholder";
  span.textContent = `${prepared.count} Zeilen eingeklappt: ${prepared.label}`;
  span.title = "Klicken oder Enter zum Aufklappen";
  span.setAttribute("role", "button");
  span.addEventListener("mousedown", (event) => {
    event.preventDefault();
    onclick(event);
  });
  return span;
}

// Zeilenweise QMD-Hervorhebung als Dekorationen; uebernimmt die
// Token-Klassen des bisherigen Overlay-Editors.
function qmdHighlighting() {
  const lineClass = (line) => {
    if (/^---\s*$/.test(line)) return "qmd-token-frontmatter";
    if (/^```/.test(line)) return "qmd-token-fence";
    if (/^\s*<!--.*-->\s*$/.test(line)) return "qmd-token-comment";
    if (/^#{1,6}\s/.test(line)) return "qmd-token-heading";
    if (isCommandLine(line)) return "qmd-token-command";
    return null;
  };

  function inlineMarks(decorations, line, offset) {
    const taken = [];
    const overlaps = (from, to) => taken.some(([start, end]) => from < end && to > start);
    const addMark = (from, to, className) => decorations.push(Decoration.mark({ class: className }).range(from, to));
    const list = line.match(/^(\s*(?:[-*+]|\d+[.)])\s+)/);
    if (list) {
      addMark(offset, offset + list[1].length, "qmd-token-list");
      taken.push([offset, offset + list[1].length]);
    }
    if (isCommandLine(line)) {
      const name = line.match(/(\\[A-Za-z@]+|:::+|!!!|@\w[\w-]*|#\|)/);
      if (name) {
        const start = offset + name.index;
        addMark(start, start + name[0].length, "qmd-token-command-name");
        taken.push([start, start + name[0].length]);
      }
      for (const match of line.matchAll(/(\{[^}]*\}|\[[^\]]*\]|\([^)]*\))/g)) {
        const start = offset + match.index;
        const end = start + match[0].length;
        if (overlaps(start, end)) continue;
        addMark(start, end, "qmd-token-command-argument");
        taken.push([start, end]);
      }
      return;
    }
    for (const match of line.matchAll(/(`[^`]+`)/g)) {
      const start = offset + match.index;
      const end = start + match[0].length;
      if (overlaps(start, end)) continue;
      addMark(start, end, "qmd-token-inline");
      taken.push([start, end]);
    }
    for (const match of line.matchAll(/(!?\[[^\]]+\]\([^)]+\))/g)) {
      const start = offset + match.index;
      const end = start + match[0].length;
      if (overlaps(start, end)) continue;
      addMark(start, end, "qmd-token-link");
      taken.push([start, end]);
    }
  }

  const build = (view) => {
    const decorations = [];
    for (const { from, to } of view.visibleRanges) {
      let position = from;
      while (position <= to) {
        const line = view.state.doc.lineAt(position);
        const className = lineClass(line.text);
        if (className) decorations.push(Decoration.line({ class: className }).range(line.from));
        inlineMarks(decorations, line.text, line.from);
        if (line.to >= to) break;
        position = line.to + 1;
      }
    }
    return Decoration.set(decorations, true);
  };

  return ViewPlugin.fromClass(
    class {
      constructor(view) {
        this.decorations = build(view);
      }
      update(update) {
        if (update.docChanged || update.viewportChanged) this.decorations = build(update.view);
      }
    },
    { decorations: instance => instance.decorations }
  );
}

function listContinuation(line) {
  const unordered = line.match(/^(\s*[-*+]\s+)/);
  if (unordered) return line.trim() ? unordered[1] : "";
  const ordered = line.match(/^(\s*)(\d+)([.)]\s+)/);
  if (!ordered) return null;
  if (!line.trim()) return "";
  return `${ordered[1]}${Number(ordered[2]) + 1}${ordered[3]}`;
}

function applyTemplate(view, from, to, template) {
  const placeholder = template.match(/\{\{(.*?)\}\}/);
  const text = template.replace(/\{\{(.*?)\}\}/g, "$1");
  let target = to;
  if (view.state.doc.sliceString(target, target + 1) === "]") target += 1;
  const anchor = from + (placeholder ? placeholder.index : text.length);
  const head = placeholder ? anchor + placeholder[1].length : anchor;
  view.dispatch({
    changes: { from, to: target, insert: text },
    selection: { anchor, head },
    scrollIntoView: true
  });
}

function bausteinCompletions(shortcuts, normalizeSearch, onShortcut) {
  return (context) => {
    const before = context.state.sliceDoc(0, context.pos);
    const match = before.match(AUTOCOMPLETE_TRIGGER);
    if (!match || match[1].length < 2) return null;
    const query = normalizeSearch(match[1]);
    const items = shortcuts
      .map((item) => {
        const label = normalizeSearch(item.label).replace(/\s+/g, "");
        const code = normalizeSearch(item.code);
        // Treffer, deren Titel mit der Eingabe beginnt, rangieren vor reinen
        // Code-Treffern: "[auf" muss "Aufgabe (Überschrift)" an erster Stelle
        // liefern, auch wenn andere Bausteine "aufgabe=" im Code enthalten.
        const byLabel = label.startsWith(query) ? 0 : 1;
        return { item, byLabel, matches: byLabel === 0 || code.includes(query) };
      })
      .filter((entry) => entry.matches)
      .sort((a, b) => a.byLabel - b.byLabel)
      .map((entry) => entry.item)
      .slice(0, AUTOCOMPLETE_LIMIT);
    if (!items.length) return null;
    return {
      // `from` zeigt auf die "[" der Ausloesung, `filter: false` stellt die
      // Options ungefiltert bereit: Das eingebaute Matching wuerde den Text
      // von `from` bis zum Cursor ("[auf") gegen die Baustein-Titel pruefen
      // und alle Treffer entfernen. Die Source filtert selbst.
      from: context.pos - match[1].length - 1,
      filter: false,
      options: items.map((item) => ({
        label: item.label,
        detail: item.code.replace(/\n/g, " "),
        // CodeMirror uebergibt (view, completion, from, to).
        apply: (view, completion, from, to) => {
          if (!onShortcut) return applyTemplate(view, from, to, item.code);
          const end = view.state.doc.sliceString(to, to + 1) === "]" ? to + 1 : to;
          closeCompletion(view);
          // Keep the trigger intact until insertion so cancelling is lossless.
          view.dispatch({ selection: { anchor: from, head: end } });
          setTimeout(() => onShortcut(item.id), 0);
        }
      })),
      validFor: /^[A-Za-zÄÖÜäöü0-9-]*$/
    };
  };
}

function editorPhrases() {
  return {
    "Find": "Suchen",
    "Replace": "Ersetzen",
    "Replace all": "Alle ersetzen",
    "Replace with": "Ersetzen mit",
    "next": "nächste",
    "previous": "vorherige",
    "all": "alle",
    "match case": "Groß-/Kleinschreibung",
    "regexp": "Regulärer Ausdruck",
    "by word": "ganze Wörter",
    "go to line": "Zur Zeile springen",
    "no matches": "keine Treffer",
    "current match": "aktueller Treffer",
    "replaced $ matches": "$ Treffer ersetzt",
    "on line": "in Zeile"
  };
}

export function create(host, options = {}) {
  const shortcuts = options.shortcuts || [];
  const normalizeSearch = options.normalizeSearch || ((value) => value.toLowerCase());
  const editableCompartment = new Compartment();
  let flashTimer = null;
  let readOnly = false;

  const enterCommand = (view) => {
    const { state } = view;
    const selection = state.selection.main;
    if (!selection.empty) return false;
    const folded = foldedRangeAt(state, selection.head);
    if (folded) {
      view.dispatch({ effects: unfoldEffect.of(folded) });
      return true;
    }
    const line = state.doc.lineAt(selection.head);
    const continuation = listContinuation(line.text.slice(0, selection.head - line.from));
    if (continuation === null) return false;
    view.dispatch({
      changes: { from: selection.head, insert: `\n${continuation}` },
      selection: { anchor: selection.head + 1 + continuation.length },
      scrollIntoView: true
    });
    return true;
  };

  const keyBindings = Prec.high(keymap.of([
    { key: "Mod-s", preventDefault: true, run: () => { options.onSave?.(); return true; } },
    { key: "Mod-Enter", preventDefault: true, run: () => { options.onRender?.(); return true; } },
    { key: "Enter", run: enterCommand },
    { key: "Tab", run: indentMore, shift: indentLess }
  ]));

  function emitStats(state) {
    const text = state.doc.toString();
    const selection = state.selection.main;
    options.onStats?.({
      lines: state.doc.lines,
      words: (text.match(/[A-Za-zÄÖÜäöüß0-9]+(?:[-'][A-Za-zÄÖÜäöüß0-9]+)*/g) || []).length,
      chars: text.length,
      selection: selection.empty ? 0 : selection.to - selection.from
    });
  }

  // Der Editorzustand wird pro Dokument neu aufgebaut (siehe setText): Die
  // Erweiterungen stehen daher als Funktion bereit.
  function buildExtensions() {
    return [
        lineNumbers(),
        diagnosticsField,
        history(),
        drawSelection(),
        highlightActiveLine(),
        EditorView.lineWrapping,
        bracketMatching(),
        closeBrackets(),
        autocompletion({ override: [bausteinCompletions(shortcuts, normalizeSearch, options.onShortcut)], icons: false }),
        indentUnit.of("  "),
        search({ top: true }),
        keymap.of(searchKeymap),
        codeFolding({
          preparePlaceholder: (state, range) => foldPlaceholderData(state, range),
          placeholderDOM: foldPlaceholderDOM
        }),
        foldGutter({ openText: "⌄", closedText: "›" }),
        foldService.of((state, lineStart) => {
          const line = state.doc.lineAt(lineStart);
          const lines = docLines(state);
          const block = foldableCommandBlock(lines, line.number - 1);
          if (!block) return null;
          return { from: lineStart, to: state.doc.line(block.end + 1).to };
        }),
        qmdHighlighting(),
        flashField,
        keyBindings,
        keymap.of(defaultKeymap),
        keymap.of(historyKeymap),
        editableCompartment.of([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
        EditorState.phrases.of(editorPhrases()),
        EditorView.contentAttributes.of({
          spellcheck: "true",
          lang: "de",
          autocapitalize: "sentences",
          autocorrect: "on"
        }),
        EditorView.domEventHandlers({
          focus: () => { options.onFocus?.(); return false; },
          dblclick: (event, view) => {
            const position = view.posAtCoords({ x: event.clientX, y: event.clientY });
            if (position == null) return false;
            const folded = foldedRangeAt(view.state, position);
            if (folded) {
              view.dispatch({ effects: unfoldEffect.of(folded) });
              return true;
            }
            const line = view.state.doc.lineAt(position);
            const lines = docLines(view.state);
            const block = foldableCommandBlock(lines, line.number - 1);
            if (!block) return false;
            view.dispatch({
              effects: foldEffect.of({ from: line.from, to: view.state.doc.line(block.end + 1).to })
            });
            return true;
          }
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) options.onInput?.();
          if (update.docChanged || update.selectionSet) emitStats(update.state);
        })
    ];
  }

  const view = new EditorView({
    parent: host,
    state: EditorState.create({ doc: "", extensions: buildExtensions() })
  });

  function flashLine(position) {
    if (flashTimer) clearTimeout(flashTimer);
    const line = view.state.doc.lineAt(position);
    view.dispatch({ effects: flashEffect.of(Decoration.set([Decoration.line({ class: "cm-flash-line" }).range(line.from)])) });
    flashTimer = setTimeout(() => {
      flashTimer = null;
      view.dispatch({ effects: flashEffect.of(null) });
    }, FLASH_MS);
  }

  function jumpToOffset(offset, length = 0) {
    const position = Math.max(0, Math.min(view.state.doc.length, offset));
    unfoldAround(view, position, position + length);
    view.dispatch({
      selection: { anchor: position, head: Math.min(view.state.doc.length, position + length) },
      effects: EditorView.scrollIntoView(position, { y: "center" })
    });
    flashLine(position);
  }

  const documentStates = new Map();
  let documentKey = "";

  return {
    getText: () => view.state.doc.toString(),
    setDiagnostics: issues => view.dispatch({ effects: diagnosticsEffect.of(issues) }),
    setText(text, setTextOptions = {}) {
      const value = String(text || "");
      const nextKey = setTextOptions.documentKey || "";
      if (documentKey && nextKey !== documentKey) {
        documentStates.delete(documentKey);
        documentStates.set(documentKey, { state: view.state, top: view.scrollDOM.scrollTop, left: view.scrollDOM.scrollLeft });
        let chars = [...documentStates.values()].reduce((sum, item) => sum + item.state.doc.length, 0);
        while (documentStates.size > 12 || chars > 2_000_000) {
          const oldest = documentStates.keys().next().value;
          chars -= documentStates.get(oldest).state.doc.length;
          documentStates.delete(oldest);
        }
      }
      const cached = nextKey && documentStates.get(nextKey);
      documentStates.delete(nextKey);
      const unchanged = nextKey && nextKey === documentKey && view.state.doc.toString() === value;
      documentKey = nextKey;
      if (unchanged) return;
      if (flashTimer) clearTimeout(flashTimer);
      flashTimer = null;
      if (cached && cached.state.doc.toString() === value) {
        view.setState(cached.state);
        view.dispatch({ effects: [
          editableCompartment.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
          diagnosticsEffect.of([]), flashEffect.of(null)
        ] });
        view.scrollDOM.scrollTop = cached.top;
        view.scrollDOM.scrollLeft = cached.left;
        emitStats(view.state);
        return;
      }
      // Neuer Editorzustand statt Transaktion: Das Laden eines Dokuments soll
      // nicht in der Rueckgaengig-Historie landen (Strg+Z springt also nie
      // zurueck auf das vorherige Dokument).
      view.setState(EditorState.create({ doc: value, extensions: buildExtensions() }));
      emitStats(view.state);
      if (setTextOptions.fold !== false) foldAllCommandBlocks(view);
    },
    insertText(value) {
      const selection = view.state.selection.main;
      view.dispatch({
        changes: { from: selection.from, to: selection.to, insert: value },
        selection: { anchor: selection.from + value.length },
        scrollIntoView: true
      });
    },
    insertTemplate(template) {
      const selection = view.state.selection.main;
      applyTemplate(view, selection.from, selection.to, template);
    },
    openSearch: () => {
      openSearchPanel(view);
      return true;
    },
    focus: () => view.focus(),
    blur: () => view.contentDOM.blur(),
    setReadOnly(value) {
      readOnly = Boolean(value);
      view.dispatch({
        effects: editableCompartment.reconfigure([
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly)
        ])
      });
    },
    setAriaLabel(label) {
      view.contentDOM.setAttribute("aria-label", label);
    },
    getSelectionStart: () => view.state.selection.main.from,
    getSelectionEnd: () => view.state.selection.main.to,
    setSelectionRange(start, end) {
      view.dispatch({
        selection: { anchor: start, head: end },
        scrollIntoView: { y: "center" }
      });
    },
    jumpToOffset,
    jumpToLine(target) {
      const number = Math.max(1, Math.min(view.state.doc.lines, Math.floor(target) || 1));
      const line = view.state.doc.line(number);
      jumpToOffset(line.from, line.text.length);
    },
    toggleFoldAtCursor() {
      const position = view.state.selection.main.head;
      const folded = foldedRangeAt(view.state, position);
      if (folded) {
        view.dispatch({ effects: unfoldEffect.of(folded) });
        return true;
      }
      const line = view.state.doc.lineAt(position);
      const range = foldable(view.state, line.from, line.to);
      if (!range) return false;
      view.dispatch({ effects: foldEffect.of(range) });
      return true;
    },
    destroy: () => {
      if (flashTimer) clearTimeout(flashTimer);
      view.destroy();
    }
  };
}
