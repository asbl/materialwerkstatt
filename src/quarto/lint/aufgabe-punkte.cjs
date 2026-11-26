"use strict";

// Custom markdownlint rule: warns when a ::: aufgabe fenced div does not
// declare a "punkte" attribute. Rendering is fine either way (the Typst/LaTeX
// templates simply omit the points badge when none is given), but an aufgabe
// box without points is usually an oversight while authoring a Klausur.

const FENCE_RE = /^(\s*)(:{3,})\s*(.*)$/;

function classTokens(rest) {
  // Brace form: ::: {.aufgabe nr="2" titel="x" punkte="5"}
  const braceMatch = rest.match(/^\{(.*)\}$/);
  if (braceMatch) {
    return { inner: braceMatch[1], hasBraces: true };
  }
  // Bare form: ::: aufgabe
  if (rest.length > 0) {
    return { inner: rest, hasBraces: false };
  }
  return null;
}

function hasAufgabeClass(inner) {
  return inner
    .split(/\s+/)
    .some((token) => token.replace(/^\./, "") === "aufgabe");
}

function hasNonEmptyPunkte(inner) {
  const match = inner.match(/punkte\s*=\s*"([^"]*)"/);
  return Boolean(match && match[1].trim() !== "");
}

module.exports = {
  names: ["aufgabe-punkte"],
  description: 'Aufgabe-Box (":::  aufgabe") ohne "punkte"-Angabe',
  tags: ["aufgabe", "quarto"],
  parser: "none",
  function: (params, onError) => {
    params.lines.forEach((line, index) => {
      const fenceMatch = line.match(FENCE_RE);
      if (!fenceMatch) {
        return;
      }
      const rest = fenceMatch[3].trim();
      const parsed = classTokens(rest);
      if (!parsed || !hasAufgabeClass(parsed.inner)) {
        return;
      }
      if (parsed.hasBraces && hasNonEmptyPunkte(parsed.inner)) {
        return;
      }
      onError({
        lineNumber: index + 1,
        detail:
          'Aufgabe-Box ohne Punkte-Angabe: "punkte" als Attribut ergaenzen (z. B. {.aufgabe nr="2" titel="..." punkte="5"}) oder bewusst ohne Punkte lassen.',
        context: line.trim(),
      });
    });
  },
};
