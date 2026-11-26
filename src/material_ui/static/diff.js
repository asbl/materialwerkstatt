// Zeilenweiser LCS-Diff mit wortgenauer Hervorhebung in geänderten Zeilen
// und eingeklappten unveränderten Bereichen. Wird vom Wiederherstellungs-
// und Versionsdialog genutzt, um Entwurf und Dateistand zu vergleichen.

const CONTEXT_LINES = 3;
const MAX_LCS_LINES = 1500;

function splitLines(text) {
  return String(text ?? "").split(/\r?\n/);
}

function lcsMatrix(a, b) {
  const rows = a.length;
  const columns = b.length;
  const table = Array.from({ length: rows + 1 }, () => new Uint32Array(columns + 1));
  for (let row = rows - 1; row >= 0; row -= 1) {
    for (let column = columns - 1; column >= 0; column -= 1) {
      table[row][column] = a[row] === b[column]
        ? table[row + 1][column + 1] + 1
        : Math.max(table[row + 1][column], table[row][column + 1]);
    }
  }
  return table;
}

export function diffLines(oldText, newText) {
  const a = splitLines(oldText);
  const b = splitLines(newText);
  let prefix = 0;
  while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < a.length - prefix && suffix < b.length - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix += 1;
  const coreA = a.slice(prefix, a.length - suffix);
  const coreB = b.slice(prefix, b.length - suffix);
  const entries = [];
  for (let index = 0; index < prefix; index += 1) entries.push({ type: "same", text: a[index] });
  if (coreA.length <= MAX_LCS_LINES && coreB.length <= MAX_LCS_LINES) {
    const table = lcsMatrix(coreA, coreB);
    let row = 0;
    let column = 0;
    while (row < coreA.length && column < coreB.length) {
      if (coreA[row] === coreB[column]) {
        entries.push({ type: "same", text: coreA[row] });
        row += 1;
        column += 1;
      } else if (table[row + 1][column] >= table[row][column + 1]) {
        entries.push({ type: "del", text: coreA[row] });
        row += 1;
      } else {
        entries.push({ type: "add", text: coreB[column] });
        column += 1;
      }
    }
    while (row < coreA.length) entries.push({ type: "del", text: coreA[row++] });
    while (column < coreB.length) entries.push({ type: "add", text: coreB[column++] });
  } else {
    for (const line of coreA) entries.push({ type: "del", text: line });
    for (const line of coreB) entries.push({ type: "add", text: line });
  }
  for (let index = suffix; index > 0; index -= 1) entries.push({ type: "same", text: a[a.length - index] });
  return entries;
}

function wordRange(oldText, newText) {
  let start = 0;
  while (start < oldText.length && start < newText.length && oldText[start] === newText[start]) start += 1;
  let end = 0;
  while (end < oldText.length - start && end < newText.length - start && oldText[oldText.length - 1 - end] === newText[newText.length - 1 - end]) end += 1;
  return { start, oldEnd: oldText.length - end, newEnd: newText.length - end };
}

function appendLine(container, entry, counterpart) {
  const line = document.createElement("div");
  line.className = `diff-line diff-line-${entry.type}`;
  const sign = document.createElement("span");
  sign.className = "diff-sign";
  sign.textContent = entry.type === "add" ? "+" : entry.type === "del" ? "−" : " ";
  line.append(sign);
  const text = document.createElement("span");
  text.className = "diff-text";
  if (counterpart) {
    const oldText = entry.type === "del" ? entry.text : counterpart.text;
    const newText = entry.type === "add" ? entry.text : counterpart.text;
    const { start, oldEnd, newEnd } = wordRange(oldText, newText);
    const end = entry.type === "del" ? oldEnd : newEnd;
    text.append(entry.text.slice(0, start));
    const changed = document.createElement("span");
    changed.className = "diff-word-changed";
    changed.textContent = entry.text.slice(start, end);
    text.append(changed, entry.text.slice(end));
  } else {
    text.textContent = entry.text;
  }
  line.append(text);
  container.append(line);
}

export function renderDiff(container, oldText, newText) {
  if (!container) return;
  container.replaceChildren();
  const entries = diffLines(oldText, newText);
  const changed = entries.filter((entry) => entry.type !== "same").length;
  const head = document.createElement("div");
  head.className = "diff-head";
  const added = entries.filter((entry) => entry.type === "add").length;
  const removed = entries.filter((entry) => entry.type === "del").length;
  head.textContent = changed
    ? `Vergleich · ${added} hinzugefügte, ${removed} entfernte Zeilen gegenüber der gespeicherten Datei`
    : "Keine Unterschiede zur gespeicherten Datei.";
  container.append(head);
  const body = document.createElement("div");
  body.className = "diff-body";
  container.append(body);
  const labels = document.createElement("div");
  labels.className = "diff-columns";
  for (const label of [container.dataset.leftLabel || "Deine noch nicht gespeicherten Änderungen", "Aktuell gespeicherte Datei"]) {
    const cell = document.createElement("strong");
    cell.textContent = label;
    labels.append(cell);
  }
  body.append(labels);

  // Pair each consecutive block of removed/added lines before selecting context,
  // so both sides stay aligned even when a block has different line counts.
  const rows = [];
  for (let index = 0; index < entries.length;) {
    const entry = entries[index];
    if (entry.type === "same") {
      rows.push({ left: entry, right: entry, changed: false });
      index += 1;
      continue;
    }
    const added = [];
    const removed = [];
    while (index < entries.length && entries[index].type !== "same") {
      const change = entries[index++];
      (change.type === "add" ? added : removed).push(change);
    }
    for (let offset = 0; offset < Math.max(added.length, removed.length); offset += 1) {
      rows.push({ left: added[offset], right: removed[offset], changed: true });
    }
  }
  const keep = new Set();
  rows.forEach((row, index) => {
    if (!row.changed) return;
    for (let position = Math.max(0, index - CONTEXT_LINES); position <= Math.min(rows.length - 1, index + CONTEXT_LINES); position += 1) {
      keep.add(position);
    }
  });
  let skip = 0;
  function appendGap() {
    if (!skip) return;
    const note = document.createElement("div");
    note.className = "diff-gap";
    note.textContent = `… ${skip} unveränderte Zeile${skip === 1 ? "" : "n"}`;
    body.append(note);
    skip = 0;
  }
  rows.forEach((row, index) => {
    if (!keep.has(index)) {
      skip += 1;
      return;
    }
    appendGap();
    const pair = document.createElement("div");
    pair.className = "diff-row";
    for (const [entry, counterpart] of [[row.left, row.right], [row.right, row.left]]) {
      if (entry) {
        appendLine(pair, entry, row.changed ? counterpart : null);
      } else {
        const empty = document.createElement("div");
        empty.className = "diff-line diff-line-empty";
        empty.setAttribute("aria-label", "Keine entsprechende Zeile");
        pair.append(empty);
      }
    }
    body.append(pair);
  });
  appendGap();
}
