// Kleiner, sicherer Markdown-Renderer fuer Chat-Antworten.
//
// Unterstuetzt: Absaetze mit Zeilenumbruechen, Ueberschriften, Aufzaehlungen, nummerierte Listen,
// Zitate, Trennlinien, Codebloecke (auch noch unvollstaendig waehrend des Streamings) sowie
// Inline-Code, **fett**, *kursiv* und [Text](https://...). Alles andere bleibt Text.
// Tabellen (GFM) und Formeln ($...$, $$...$$, \(...\), \[...\]; siehe tex.js) werden ebenfalls
// dargestellt. Es wird nie HTML aus dem Modelltext interpretiert: parseMarkdown liefert reine Daten,
// renderMarkdown baut daraus DOM-Knoten ueber createElement/textContent.

import { parseTex, renderTex } from "./tex.js";

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$/;

export function isSafeUrl(url) {
  return /^https?:\/\/[^\s<>"']+$/i.test(url);
}

// -- Inline ---------------------------------------------------------------------------

const INLINE = [
  { type: "code", pattern: /^`([^`\n]+)`/ },
  // Formel; "5 $ und 6 $" oder "$5" (Geld) bleiben Text: nach dem Anfang kein Leerzeichen, vor dem Ende
  // keins und nach dem Ende keine Ziffer.
  { type: "math", pattern: /^\$(?![\s$])([^\s$](?:[^$\n]*?[^\s$])?)\$(?![\d$])/ },
  { type: "strong", pattern: /^\*\*(?=\S)([\s\S]*?\S)\*\*/ },
  { type: "strong", pattern: /^__(?=\S)([\s\S]*?\S)__(?![\w])/ },
  { type: "em", pattern: /^\*([^\s*](?:[^*\n]*[^\s*])?)\*(?!\*)/ },
  { type: "em", pattern: /^_([^\s_](?:[^_\n]*[^\s_])?)_(?!\w)/ },
  { type: "link", pattern: /^\[([^\]\n]+)\]\(([^)\s]+)\)/ },
];

export function parseInline(text) {
  const nodes = [];
  let buffer = "";
  let rest = text;
  const flush = () => {
    if (buffer) nodes.push({ type: "text", text: buffer });
    buffer = "";
  };
  while (rest) {
    const parenMath = /^\\\(([\s\S]+?)\\\)/.exec(rest);
    if (parenMath) {
      flush();
      nodes.push({ type: "math", text: parenMath[1] });
      rest = rest.slice(parenMath[0].length);
      continue;
    }
    // Maskierte Zeichen bleiben als Zeichen erhalten.
    if (rest[0] === "\\" && rest.length > 1 && /[\\`*_[\]()#>~-]/.test(rest[1])) {
      buffer += rest[1];
      rest = rest.slice(2);
      continue;
    }
    let matched = false;
    if (/[`*_[$]/.test(rest[0])) {
      const intraword = /\w$/.test(buffer);
      for (const { type, pattern } of INLINE) {
        // Kursiv mitten im Wort (snake_case, 2*3*4) ist keine Hervorhebung.
        if (type === "em" && intraword) continue;
        const match = pattern.exec(rest);
        if (!match) continue;
        if (type === "link" && !isSafeUrl(match[2])) continue;
        flush();
        if (type === "code" || type === "math") nodes.push({ type, text: match[1] });
        else if (type === "link") nodes.push({ type, href: match[2], children: parseInline(match[1]) });
        else nodes.push({ type, children: parseInline(match[1]) });
        rest = rest.slice(match[0].length);
        matched = true;
        break;
      }
    }
    if (!matched) {
      buffer += rest[0];
      rest = rest.slice(1);
    }
  }
  flush();
  return nodes;
}

// -- Bloecke --------------------------------------------------------------------------

export function parseMarkdown(source) {
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;
  const startsBlock = (line) => FENCE.test(line) || HEADING.test(line) || BULLET.test(line) || ORDERED.test(line) || QUOTE.test(line) || RULE.test(line) || /^\s*(\$\$|\\\[)/.test(line);
  const tableAt = (at) => lines[at]?.includes("|") && TABLE_SEPARATOR.test(lines[at + 1] ?? "");

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const body = [];
      index += 1;
      while (index < lines.length && !(lines[index].trim().startsWith(marker[0].repeat(marker.length)) && /^\s*[`~]+\s*$/.test(lines[index]))) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1; // schliessende Zeile (fehlt sie noch, endet der Block mit dem Text)
      blocks.push({ type: "code", language: fence[2] || "", text: body.join("\n") });
      continue;
    }
    const displayMath = /^\s*(\$\$|\\\[)/.exec(line);
    if (displayMath) {
      const close = displayMath[1] === "$$" ? "$$" : "\\]";
      const rest = line.slice(line.indexOf(displayMath[1]) + displayMath[1].length);
      const body = [];
      if (rest.includes(close)) body.push(rest.slice(0, rest.lastIndexOf(close)));
      else {
        body.push(rest);
        index += 1;
        while (index < lines.length && !lines[index].includes(close)) { body.push(lines[index]); index += 1; }
        if (index < lines.length) body.push(lines[index].slice(0, lines[index].lastIndexOf(close)));
      }
      index += 1;
      blocks.push({ type: "math", text: body.join("\n").trim() });
      continue;
    }
    if (tableAt(index)) {
      const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
      const align = cells(lines[index + 1]).map((cell) => (cell.startsWith(":") && cell.endsWith(":") ? "center" : cell.endsWith(":") ? "right" : cell.startsWith(":") ? "left" : ""));
      const header = cells(line).map(parseInline);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
        rows.push(cells(lines[index]).map(parseInline));
        index += 1;
      }
      blocks.push({ type: "table", align, header, rows });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, children: parseInline(heading[2]) });
      index += 1;
      continue;
    }
    if (RULE.test(line)) { blocks.push({ type: "rule" }); index += 1; continue; }

    if (BULLET.test(line) || ORDERED.test(line)) {
      const ordered = ORDERED.test(line) && !BULLET.test(line);
      const items = [];
      let start = ordered ? Number(ORDERED.exec(line)[1]) : 1;
      while (index < lines.length) {
        const current = lines[index];
        const match = ordered ? ORDERED.exec(current) : BULLET.exec(current);
        if (match) {
          items.push(parseInline(ordered ? match[2] : match[1]));
          index += 1;
        } else if (current.trim() && /^\s{2,}\S/.test(current) && items.length && !startsBlock(current.trim())) {
          // Fortsetzungszeile eines Listenpunkts
          items[items.length - 1].push({ type: "break" }, ...parseInline(current.trim()));
          index += 1;
        } else {
          break;
        }
      }
      blocks.push({ type: "list", ordered, start, items });
      continue;
    }
    if (QUOTE.test(line)) {
      const body = [];
      while (index < lines.length && QUOTE.test(lines[index])) { body.push(QUOTE.exec(lines[index])[1]); index += 1; }
      blocks.push({ type: "quote", children: parseInline(body.join("\n")) });
      continue;
    }
    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !(paragraph.length && (startsBlock(lines[index]) || tableAt(index)))) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", children: parseInline(paragraph.join("\n")) });
  }
  return blocks;
}

// -- DOM ------------------------------------------------------------------------------

function inlineToDom(nodes, doc, parent) {
  for (const node of nodes) {
    if (node.type === "text") {
      const parts = node.text.split("\n");
      parts.forEach((part, position) => {
        if (position) parent.append(doc.createElement("br"));
        if (part) parent.append(doc.createTextNode(part));
      });
    } else if (node.type === "break") {
      parent.append(doc.createElement("br"));
    } else if (node.type === "math") {
      const element = doc.createElement("span");
      element.className = "chat-math";
      element.title = node.text;
      renderTex(parseTex(node.text), doc, element);
      parent.append(element);
    } else if (node.type === "code") {
      const element = doc.createElement("code");
      element.textContent = node.text;
      parent.append(element);
    } else if (node.type === "link") {
      const element = doc.createElement("a");
      element.href = node.href;
      element.target = "_blank";
      element.rel = "noopener noreferrer";
      inlineToDom(node.children, doc, element);
      parent.append(element);
    } else {
      const element = doc.createElement(node.type);
      inlineToDom(node.children, doc, element);
      parent.append(element);
    }
  }
}

export function renderMarkdown(source, doc = document) {
  const fragment = doc.createDocumentFragment();
  for (const block of parseMarkdown(source)) {
    let element;
    if (block.type === "paragraph") {
      element = doc.createElement("p");
      inlineToDom(block.children, doc, element);
    } else if (block.type === "heading") {
      element = doc.createElement(`h${Math.min(6, block.level + 2)}`);
      inlineToDom(block.children, doc, element);
    } else if (block.type === "list") {
      element = doc.createElement(block.ordered ? "ol" : "ul");
      if (block.ordered && block.start !== 1) element.start = block.start;
      for (const item of block.items) {
        const li = doc.createElement("li");
        inlineToDom(item, doc, li);
        element.append(li);
      }
    } else if (block.type === "quote") {
      element = doc.createElement("blockquote");
      inlineToDom(block.children, doc, element);
    } else if (block.type === "math") {
      element = doc.createElement("div");
      element.className = "chat-math chat-math-display";
      element.title = block.text;
      renderTex(parseTex(block.text), doc, element);
    } else if (block.type === "table") {
      element = doc.createElement("table");
      const head = doc.createElement("thead");
      const headRow = doc.createElement("tr");
      block.header.forEach((cell, column) => {
        const th = doc.createElement("th");
        if (block.align[column]) th.style.textAlign = block.align[column];
        inlineToDom(cell, doc, th);
        headRow.append(th);
      });
      head.append(headRow);
      const body = doc.createElement("tbody");
      for (const row of block.rows) {
        const tr = doc.createElement("tr");
        block.header.forEach((_, column) => {
          const td = doc.createElement("td");
          if (block.align[column]) td.style.textAlign = block.align[column];
          inlineToDom(row[column] ?? [], doc, td);
          tr.append(td);
        });
        body.append(tr);
      }
      element.append(head, body);
    } else if (block.type === "code") {
      element = doc.createElement("pre");
      const code = doc.createElement("code");
      if (block.language) code.dataset.language = block.language;
      code.textContent = block.text;
      element.append(code);
    } else {
      element = doc.createElement("hr");
    }
    fragment.append(element);
  }
  return fragment;
}
