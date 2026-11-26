// Zeilenweiser Diff fuer Aenderungsvorschlaege (reine Funktionen, ohne DOM).

const MAX_LINES = 400;

// Liefert eine Liste {type: "ctx" | "add" | "del", text} in Dokumentreihenfolge.
export function lineDiff(oldText, newText) {
  const a = String(oldText ?? "").split("\n");
  const b = String(newText ?? "").split("\n");
  // Gemeinsame Anfaenge und Enden abtrennen; dann bleibt meist nur ein kleiner Kern.
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;
  const coreA = a.slice(head, a.length - tail);
  const coreB = b.slice(head, b.length - tail);
  const ops = a.slice(0, head).map((text) => ({ type: "ctx", text }));
  if (coreA.length > MAX_LINES || coreB.length > MAX_LINES) {
    // Zu gross fuer die quadratische LCS-Tabelle: ganzer Block als Ersatz.
    ops.push(...coreA.map((text) => ({ type: "del", text })), ...coreB.map((text) => ({ type: "add", text })));
  } else {
    const n = coreA.length;
    const m = coreB.length;
    const table = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i -= 1) {
      for (let j = m - 1; j >= 0; j -= 1) {
        table[i][j] = coreA[i] === coreB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && coreA[i] === coreB[j]) { ops.push({ type: "ctx", text: coreA[i] }); i += 1; j += 1; }
      // Bei Gleichstand zuerst loeschen, dann hinzufuegen (gewohnte Lesereihenfolge).
      else if (i < n && (j === m || table[i + 1][j] >= table[i][j + 1])) { ops.push({ type: "del", text: coreA[i] }); i += 1; }
      else { ops.push({ type: "add", text: coreB[j] }); j += 1; }
    }
  }
  ops.push(...a.slice(a.length - tail).map((text) => ({ type: "ctx", text })));
  return ops;
}

// Faltet lange unveraenderte Strecken zu {type: "skip", count} zusammen (je `keep` Zeilen Umgebung).
export function collapseContext(ops, keep = 2) {
  const visible = new Array(ops.length).fill(false);
  ops.forEach((op, index) => {
    if (op.type === "ctx") return;
    for (let k = Math.max(0, index - keep); k <= Math.min(ops.length - 1, index + keep); k += 1) visible[k] = true;
  });
  const result = [];
  let skipped = 0;
  ops.forEach((op, index) => {
    if (visible[index] || !ops.some((item) => item.type !== "ctx")) {
      if (skipped) { result.push({ type: "skip", count: skipped }); skipped = 0; }
      result.push(op);
    } else {
      skipped += 1;
    }
  });
  if (skipped) result.push({ type: "skip", count: skipped });
  return result;
}
