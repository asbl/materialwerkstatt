// Leichtgewichtige TeX-Darstellung fuer Schulmathematik im Chat (ohne KaTeX).
//
// Unterstuetzt Hoch-/Tiefstellung, \frac, \sqrt, \text, Griechisch und die gaengigen Zeichen
// (\cdot, \times, \le, \neq ...). Unbekannte Befehle bleiben als Text sichtbar. Reine Funktionen:
// parseTex liefert Daten, renderTex baut daraus DOM-Knoten (kein innerHTML).

const SYMBOLS = {
  cdot: "·", times: "×", div: "÷", pm: "±", mp: "∓", le: "≤", leq: "≤", ge: "≥", geq: "≥", neq: "≠", ne: "≠",
  approx: "≈", equiv: "≡", infty: "∞", pi: "π", alpha: "α", beta: "β", gamma: "γ", delta: "δ", Delta: "Δ",
  epsilon: "ε", varepsilon: "ε", theta: "θ", lambda: "λ", mu: "μ", sigma: "σ", Sigma: "Σ", omega: "ω", Omega: "Ω",
  varphi: "φ", phi: "φ", rho: "ρ", tau: "τ", to: "→", rightarrow: "→", leftarrow: "←", Rightarrow: "⇒",
  Leftarrow: "⇐", leftrightarrow: "↔", Leftrightarrow: "⇔", in: "∈", notin: "∉", subset: "⊂", cup: "∪", cap: "∩",
  cdots: "⋯", ldots: "…", dots: "…", circ: "°", degree: "°", angle: "∠", perp: "⊥", parallel: "∥", sum: "∑",
  prod: "∏", int: "∫", sin: "sin", cos: "cos", tan: "tan", log: "log", ln: "ln", lim: "lim", max: "max", min: "min",
  mathbb: "", quad: "  ", qquad: "    ", ",": " ", ";": " ", ":": " ", " ": " ", "!": "", "%": "%", "&": "&",
  "#": "#", "$": "$", "{": "{", "}": "}", "_": "_",
};
const TEXT_COMMANDS = new Set(["text", "mathrm", "textbf", "textit", "mathbf", "mathit", "operatorname", "mbox"]);
const SIZE_COMMANDS = new Set(["left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "textstyle"]);
const MAX_DEPTH = 8;
const MAX_LENGTH = 2000;

export function parseTex(source) {
  const src = String(source ?? "").slice(0, MAX_LENGTH);
  let pos = 0;

  function readAtom(depth) {
    while (src[pos] === " ") pos += 1;
    if (pos >= src.length) return [];
    if (src[pos] === "{") {
      pos += 1;
      const children = parseSequence(depth + 1, "}");
      if (src[pos] === "}") pos += 1;
      return children;
    }
    if (src[pos] === "\\") return parseCommand(depth);
    const char = src[pos];
    pos += 1;
    return [{ t: "text", text: char }];
  }

  function parseCommand(depth) {
    pos += 1; // Backslash
    let name = "";
    while (pos < src.length && /[A-Za-z]/.test(src[pos])) { name += src[pos]; pos += 1; }
    if (!name) { name = src[pos] ?? ""; pos += 1; }
    if (name === "\\") return [{ t: "text", text: " " }];
    if (name === "frac" || name === "dfrac" || name === "tfrac") {
      return [{ t: "frac", num: readAtom(depth + 1), den: readAtom(depth + 1) }];
    }
    if (name === "sqrt") {
      if (src[pos] === "[") { const end = src.indexOf("]", pos); pos = end < 0 ? src.length : end + 1; }
      return [{ t: "sqrt", children: readAtom(depth + 1) }];
    }
    if (TEXT_COMMANDS.has(name)) return [{ t: "group", children: readAtom(depth + 1) }];
    if (SIZE_COMMANDS.has(name)) return [];
    if (Object.hasOwn(SYMBOLS, name)) return [{ t: "text", text: SYMBOLS[name] }];
    return [{ t: "text", text: `\\${name}` }];
  }

  function parseSequence(depth, until) {
    const nodes = [];
    let buffer = "";
    const flush = () => { if (buffer) nodes.push({ t: "text", text: buffer }); buffer = ""; };
    while (pos < src.length && src[pos] !== until) {
      if (depth > MAX_DEPTH) { buffer += src[pos]; pos += 1; continue; }
      const char = src[pos];
      if (char === "^" || char === "_") {
        pos += 1;
        flush();
        nodes.push({ t: char === "^" ? "sup" : "sub", children: readAtom(depth + 1) });
      } else if (char === "{") {
        flush();
        nodes.push(...readAtom(depth));
      } else if (char === "\\") {
        flush();
        nodes.push(...parseCommand(depth));
      } else if (char === "&") {
        pos += 1;
      } else {
        buffer += char;
        pos += 1;
      }
    }
    flush();
    return nodes;
  }

  return parseSequence(0, "");
}

export function renderTex(nodes, doc, parent) {
  for (const node of nodes) {
    if (node.t === "text") {
      parent.append(doc.createTextNode(node.text));
    } else if (node.t === "sup" || node.t === "sub") {
      const element = doc.createElement(node.t);
      renderTex(node.children, doc, element);
      parent.append(element);
    } else if (node.t === "group") {
      renderTex(node.children, doc, parent);
    } else if (node.t === "frac") {
      const frac = doc.createElement("span");
      frac.className = "chat-frac";
      const num = doc.createElement("span");
      num.className = "chat-frac-num";
      const den = doc.createElement("span");
      den.className = "chat-frac-den";
      renderTex(node.num, doc, num);
      renderTex(node.den, doc, den);
      frac.append(num, den);
      parent.append(frac);
    } else if (node.t === "sqrt") {
      const root = doc.createElement("span");
      root.className = "chat-sqrt";
      root.append(doc.createTextNode("√"));
      const body = doc.createElement("span");
      body.className = "chat-sqrt-body";
      renderTex(node.children, doc, body);
      root.append(body);
      parent.append(root);
    }
  }
}

// Reiner Text einer Formel (fuer Kopieren, Tests und Bildschirmleser).
export function texToText(nodes) {
  return nodes.map((node) => {
    if (node.t === "text") return node.text;
    if (node.t === "sup") return `^${texToText(node.children)}`;
    if (node.t === "sub") return `_${texToText(node.children)}`;
    if (node.t === "group") return texToText(node.children);
    if (node.t === "frac") return `(${texToText(node.num)})/(${texToText(node.den)})`;
    if (node.t === "sqrt") return `√(${texToText(node.children)})`;
    return "";
  }).join("");
}
