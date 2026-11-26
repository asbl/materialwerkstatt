const ink = "#172033";
const blue = "#0f4a64";

function textLine(left, top, content, size = 11, bold = false, fill = null) {
  return `<text x="${left}" y="${top}" font-size="${size}"${bold ? ' font-weight="700"' : ""}${fill ? ` fill="${fill}"` : ""}>${content}</text>`;
}

function rule(left, top, width, color = "#aab2bc") {
  return `<path d="M${left} ${top}h${width}" stroke="${color}" stroke-width="0.7"/>`;
}

function band(top, title, color = "#e8edf1") {
  return `<rect x="28" y="${top}" width="364" height="25" fill="${color}"/>${textLine(36, top + 17, title, 12, true)}`;
}

function answerLines(top, count = 3) {
  return Array.from({ length: count }, (_, index) => rule(28, top + index * 22, 364)).join("");
}

function task(top, title, points) {
  return textLine(28, top, title, 12, true) + textLine(360, top, points, 10);
}

function grid(top) {
  return `<g stroke="#bac1c8" stroke-width="0.5">${
    Array.from({ length: 27 }, (_, index) => `<path d="M${28 + index * 14} ${top}v112"/>`).join("")
  }${Array.from({ length: 9 }, (_, index) => `<path d="M28 ${top + index * 14}h364"/>`).join("")}</g>`;
}

function assessment(title, oral = false) {
  return textLine(28, 48, title, 21, true)
    + textLine(28, 80, "Name: ____________________     Datum: __________", 10)
    + band(104, oral ? "Schriftlicher Teil · 30 Minuten" : "Bearbeitungszeit: 45 Minuten")
    + textLine(36, 149, "Hilfsmittel: Lineal, Taschenrechner", 10)
    + task(193, "1   Grundlagen anwenden", "6 P")
    + textLine(28, 218, "Beschreibe deinen Lösungsweg.") + answerLines(246)
    + task(330, oral ? "2   Mündlicher Teil · Begründen" : "2   Zusammenhänge erklären", "8 P")
    + textLine(28, 355, "Vergleiche die beiden Lösungsansätze.") + answerLines(383)
    + band(466, "Bewertung")
    + textLine(36, 513, "Punkte: ____ / 14         Note: ____", 11)
    + rule(28, 550, 164) + textLine(28, 566, "Unterschrift", 9);
}

function supportPlan() {
  return textLine(28, 43, "Christian-Wirth-Schule", 19, true)
    + textLine(28, 61, "Individueller Förderplan", 11) + rule(28, 73, 364, ink)
    + band(88, "Förderplan für: Beispielkind")
    + textLine(36, 134, "Klasse: 5    Schuljahr: 2026/27    Fach: Mathematik", 10)
    + textLine(36, 156, "Verfasser/in: __________    Datum: __________", 10)
    + [184, 324].map((top, index) => band(top, `Förderbereich: ${index ? "Arbeitsverhalten" : "Rechenstrategien"}`, "#d9d9d9")
      + `<rect x="28" y="${top + 31}" width="364" height="91" fill="none" stroke="#777" stroke-width="0.7"/>
        <path d="M130 ${top + 31}v91M252 ${top + 31}v91" stroke="#777" stroke-width="0.7"/>`
      + rule(28, top + 55, 364, "#777")
      + textLine(34, top + 47, "Ausgangslage", 9, true)
      + textLine(136, top + 47, "Ziele / Maßnahmen", 9, true)
      + textLine(258, top + 47, "Beobachtung", 9, true)
      + textLine(34, top + 77, index ? "Konzentration" : "Zahlverständnis", 9)
      + textLine(136, top + 77, index ? "Arbeit strukturieren" : "Strategien üben", 9)
      + textLine(258, top + 77, "Fortschritte …", 9)).join("")
    + [28, 156, 284].map((left, index) => rule(left, 514, 108, ink)
      + textLine(left, 531, ["Lehrer/in", "Erziehungsberechtigte", "Schüler/in"][index], 8)).join("");
}

const layouts = {
  "latex-template.tex": () => textLine(28, 48, "Brüche verstehen", 23, true)
    + textLine(28, 75, "Arbeitsblatt · Mathematik", 11)
    + task(119, "1   Anteile erkennen", "")
    + textLine(28, 145, "Welcher Anteil ist gefärbt? Begründe.")
    + `<rect x="64" y="171" width="104" height="78" fill="#e8edf1" stroke="${ink}"/>
       <path d="M116 171v78M64 210h104" stroke="${ink}"/>
       <rect x="65" y="172" width="50" height="37" fill="#7e9db1"/>`
    + answerLines(281, 2)
    + task(349, "2   Eigene Beispiele finden", "")
    + textLine(28, 375, "Zeichne und beschrifte einen weiteren Bruch.")
    + answerLines(423, 5),
  "slides-template.tex": () => textLine(28, 48, "Brüche im Alltag", 25, true)
    + rule(28, 67, 364, blue)
    + textLine(32, 106, "Wie teilen wir gerecht?", 17)
    + `<circle cx="118" cy="174" r="43" fill="#dbe8ef" stroke="${blue}"/>
       <path d="M118 131v86M75 174h86" stroke="${blue}" stroke-width="2"/>`
    + textLine(205, 164, "• Anteile erkennen", 14)
    + textLine(205, 193, "• Lösungen vergleichen", 14)
    + rule(28, 264, 364, blue)
    + textLine(28, 282, "Mathematik · Brüche", 9) + textLine(380, 282, "2", 9),
  "exam-template.typst": () => assessment("Klausur · Mathematik"),
  "nachpruefung-template.typst": () => assessment("Nachprüfung", true),
  "math-test-template.typst": () => textLine(28, 48, "Mathe-Test · Rechnen", 21, true)
    + textLine(28, 80, "Name: ____________________     Datum: __________", 10)
    + task(125, "1   Berechne im Kopf.", "4 P")
    + textLine(28, 156, "a) 48 + 27 = ______     b) 6 · 12 = ______")
    + answerLines(190, 2)
    + task(261, "2   Zeige deinen Rechenweg.", "6 P")
    + textLine(28, 288, "Berechne 324 : 6. Nutze das Rechengitter.")
    + grid(311) + band(466, "Punkte: ____ / 10         Note: ____")
    + rule(28, 550, 164) + textLine(28, 566, "Unterschrift", 9),
  "foerderplan-template.typst": supportPlan,
};

function iconBoxSymbol(svg, left, top, size) {
  return `<svg x="${left}" y="${top}" width="${size}" height="${size}" viewBox="0 0 64 64">${svg.replace(/^<svg[^>]*>|<\/svg>$/g, "")}</svg>`;
}

function iconBoxWorksheetPreview(design) {
  const box = (top, title, kind, body, tint) => `
    <rect x="30" y="${top + 2}" width="362" height="61" fill="${design.ink}"/>
    <rect x="28" y="${top}" width="362" height="61" fill="${tint}" stroke="${design.primary}"/>
    ${iconBoxSymbol(design.box_icons[kind], 35, top + 5, 20)}
    ${textLine(63, top + 21, title, 12, true)}
    ${textLine(36, top + 46, body, 10)}`;
  return `<rect x="28" y="25" width="364" height="80" fill="${design.paper}" stroke="${design.primary}"/>
    ${textLine(40, 58, "Deine Lernmission", 20, true, design.primary)}
    ${textLine(40, 84, "Mathematik · Üben und entdecken", 10)}
    ${iconBoxSymbol(design.motif, 349, 38, 30)}
    ${textLine(28, 132, "Name: __________________    Datum: ______", 10)}
    <rect x="30" y="154" width="225" height="29" fill="${design.ink}"/>
    <rect x="28" y="152" width="225" height="29" fill="${design.accent}" stroke="${design.ink}"/>
    ${textLine(36, 172, "1   Entdecke das Muster", 13, true)}
    ${box(198, "Merke", "infobox", "Vier Viertel ergeben ein Ganzes.", design.paper)}
    ${box(271, "Tipp", "tippbox", "Zeichne vier gleich große Teile.", "#eef7ec")}
    ${box(344, "Achtung", "warnbox", "Vergleiche gleich große Teile.", "#fff0e5")}
    <rect x="28" y="423" width="364" height="98" fill="white" stroke="#666" stroke-dasharray="4 3"/>
    ${rule(28, 565, 364, design.primary)}${textLine(384, 582, "1", 8, false, design.primary)}`;
}

function iconBoxSlidePreview(design) {
  const frame = design.slide_background;
  const slides = [
    frame + iconBoxSymbol(design.motif, 725, 270, 150)
      + `<text x="800" y="530" text-anchor="middle" font-family="monospace" font-size="70" font-weight="700" fill="${design.primary}">Brüche entdecken</text>`
      + `<text x="800" y="620" text-anchor="middle" font-size="38">Mathematik · Klasse 5</text>`,
    frame + textLine(64, 118, "Was fällt dir auf?", 60, true)
      + iconBoxSymbol(design.motif, 1450, 48, 70)
      + `<rect x="100" y="260" width="440" height="300" fill="${design.paper}" stroke="${design.ink}" stroke-width="4"/>
         <rect x="100" y="260" width="220" height="150" fill="${design.accent}"/>
         <path d="M320 260v300M100 410h440" stroke="${design.ink}" stroke-width="4"/>
         <rect x="685" y="265" width="810" height="270" fill="${design.ink}"/>
         <rect x="680" y="260" width="810" height="270" fill="${design.paper}" stroke="${design.primary}" stroke-width="3"/>`
      + iconBoxSymbol(design.box_icons.infobox, 710, 280, 80)
      + textLine(820, 340, "Merke", 42, true, design.primary)
      + textLine(710, 440, "Vier Teile ergeben ein Ganzes.", 36)
      + textLine(64, 720, "Wie teilst du gerecht?", 42)
      + textLine(64, 875, "Brüche entdecken", 22)
      + textLine(1500, 875, "1", 22),
  ];
  return `<figure class="template-layout-preview template-slide-preview">${slides.map((content, index) => `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" role="img" aria-label="${index ? "Inhaltsfolie" : "Titelfolie"}: Layout mit Symbolkästen" style="font-family: Arial, sans-serif; fill: ${design.ink}">${content}</svg>`).join("")}
    <figcaption>16:9 · Pixelüberschriften · klare Lernboxen · freie Zeichenfläche.</figcaption></figure>`;
}

function designLayout(design) {
  if (design.box_icons) return iconBoxWorksheetPreview(design);
  const pixel = Boolean(design.pixel);
  const headingInk = design.preview_heading_ink || design.ink;
  const heading = (top, title) => `<rect x="28" y="${top}" width="364" height="30" rx="${design.radius}" fill="${pixel ? design.accent : design.paper}"/>
    ${pixel ? `<rect x="28" y="${top}" width="364" height="30" fill="none" stroke="${design.ink}"/>
      <path d="M28 ${top + 30}h364v-30" fill="none" stroke="${design.ink}" stroke-width="2"/>`
      : `<path d="M29 ${top}v30" stroke="${design.primary}" stroke-width="3"/>`}${textLine(38, top + 21, title, 13, true, headingInk)}`;
  return `<rect x="28" y="25" width="364" height="80" rx="${design.radius}" fill="${design.paper}" stroke="${design.primary}"/>
    <g fill="${design.primary}">${textLine(40, 58, "Deine Lernmission", 21, true)}</g>
    ${textLine(40, 84, "Mathematik · Üben und entdecken", 10)}
    ${textLine(28, 135, "Name: __________________    Klasse: ______", 10)}
    ${heading(158, "1   Entdecke das Muster")}
    ${textLine(28, 212, "Rechne und erkläre deinen Lösungsweg.")}
    ${textLine(28, 238, "24 + 18 = ______       36 + 27 = ______")}
    ${answerLines(265, 2)}
    <rect x="28" y="312" width="364" height="58" rx="${design.radius}" fill="${design.id === "foerdermaterial" ? "#e3ebff" : design.paper}" stroke="${design.primary}"/>
    ${pixel ? `<path d="M28 370h364v-58" fill="none" stroke="${design.ink}" stroke-width="2"/>` : ""}
    <g fill="${design.primary}">${textLine(38, 334, "Info", 12, true)}</g>
    <svg x="38" y="342" width="14" height="14" viewBox="0 0 64 58" data-design-motif="info">${design.motif.replace(/^<svg[^>]*>|<\/svg>$/g, "")}</svg>
    ${textLine(60, 355, "Nutze eine Strategie, die du schon kennst.", 10)}
    ${heading(390, "2   Jetzt bist du dran")}${grid(433)}
    ${rule(28, 565, 364, design.primary)}
    <g fill="${design.primary}">${textLine(384, 582, "1", 8)}</g>`;
}

function slideLayoutPreview(design) {
  if (design?.box_icons) return iconBoxSlidePreview(design);
  const palette = design || { primary: "#172033", paper: "#ffffff", ink: "#172033", accent: "#eeeeee", radius: 0, label: "Standard" };
  const pixel = design && Boolean(design.pixel);
  const woolly = Boolean(design?.box_mascot);
  const frame = title => `<rect width="1600" height="900" fill="${palette.paper}"/>
    ${design ? design.slide_background : ""}
    ${textLine(64, 120, title, 64, true)}
    ${design ? `<g fill="${palette.primary}">${woolly ? textLine(1510, 876, "1", 20) : textLine(40, 876, palette.label, 20)}</g>` : ""}`;
  const slides = [
    frame("Brüche entdecken") + textLine(64, 252, "Mathematik · Klasse 5", 36)
      + textLine(64, 390, "Wie teilen wir gerecht?", 44),
    frame("Was fällt dir auf?")
      + `<rect x="96" y="240" width="480" height="320" fill="${palette.paper}" stroke="${palette.ink}" stroke-width="4"/>
        <rect x="96" y="240" width="240" height="160" fill="${palette.accent}"/>
        <path d="M336 240v320M96 400h480" stroke="${palette.ink}" stroke-width="4"/>`
      + (woolly ? `<rect x="680" y="240" width="820" height="280" rx="30" fill="${palette.paper}" stroke="${palette.primary}" stroke-width="3"/>
        <svg x="700" y="270" width="150" height="170" viewBox="0 0 180 200">${design.box_mascot.replace(/^<svg[^>]*>|<\/svg>$/g, "")}</svg>
        ${textLine(880, 310, "Das Maskottchen erklärt", 36, true, palette.primary)}
        ${textLine(880, 380, "Vier gleiche Teile.", 32)}
        ${textLine(880, 435, "Ein Teil ist gefärbt.", 32)}`
        : textLine(720, 330, "Ein Ganzes – vier Teile", 36))
      + textLine(64, 700, "Welchen Anteil siehst du?", 44),
  ];
  return `<figure class="template-layout-preview template-slide-preview">${slides.map((content, index) => `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" role="img" aria-label="${index ? "Inhaltsfolie" : "Titelfolie"}: Layoutbeispiel" style="font-family: ${pixel ? "monospace" : "Arial, sans-serif"}; fill: ${palette.ink}">${content}</svg>`).join("")}
    <figcaption>Titelfolie und Inhaltsfolie · 16:9<br>Designrahmen mit freier Zeichenfläche, Modell und Gesprächsimpuls.</figcaption>
  </figure>`;
}

export function templateLayoutPreview(path, design, target) {
  if (target === "slides") return slideLayoutPreview(design);
  const filename = path.split("/").pop();
  const layout = design ? () => designLayout(design) : layouts[filename];
  if (!layout) return "";
  const landscape = filename === "slides-template.tex";
  return `<figure class="template-layout-preview">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 ${landscape ? 305 : 594}" role="img" aria-label="Schematische Layoutvorschau mit Beispielinhalten" style="font-family: Arial, sans-serif; fill: ${ink}">
      <rect width="420" height="${landscape ? 305 : 594}" fill="white"/>
      ${layout()}
    </svg>
    <figcaption>Layoutbeispiel · schematisch<br>Inhalt und Seitenumbrüche hängen vom Dokument ab.</figcaption>
  </figure>`;
}
