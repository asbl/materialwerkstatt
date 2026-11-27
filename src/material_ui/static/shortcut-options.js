// Field descriptions complement the example values in the shortcut catalogue.
const LABELS = {
  "schuelerdialog-farben": ["Name 1", "Haarfarbe 1", "Hautfarbe 1", "Akzentfarbe 1", "Aussage 1", "Name 2", "Haarfarbe 2", "Hautfarbe 2", "Akzentfarbe 2", "Aussage 2"],
  "modell-schriftlich": ["Malaufgabe", "Nullzeile (ja/nein)", "Bildbreite (10–250 mm)"],
  "schuelerdialog-zwei": ["Name 1", "Figur 1", "Aussage 1", "Name 2", "Figur 2", "Aussage 2"],
  "schuelerdialog-drei": ["Name 1", "Figur 1", "Aussage 1", "Name 2", "Figur 2", "Aussage 2", "Name 3", "Figur 3", "Aussage 3"],
  "schuelerdialog-modelle": ["Name 1", "Figur 1", "Aussage 1", "Inhalt unter Beitrag 1", "Name 2", "Figur 2", "Aussage 2", "Inhalt unter Beitrag 2"],
  "modell-ziffernraetsel": ["Malaufgabe mit Lücken (_ oder ?)", "Vorgegebenes Ergebnis", "Bildbreite (10–250 mm)"],
  "aufgabe-ueberschrift": ["Aufgabennummer", "Kurztitel", "Punkte"],
  teilaufgabe: ["Buchstabe", "Punkte"],
  fortsetzung: ["Aufgabennummer", "Kurztitel"],
  "antwortlinie-breite": ["Breite (z. B. 3cm)"],
  eingabetabelle: ["Zeilenhöhe (z. B. 1cm)"],
  schreiblinien: ["Anzahl der Linien (1–30)"],
  antwortkasten: ["Höhe (z. B. 3cm)"],
  platz: ["Breite (z. B. 1cm)"],
  rechengitter: ["Kästchengröße in cm", "Zeilen", "Spalten (nur LaTeX)"],
  einheitskreis: ["Winkel in Grad"],
  "einheitskreis-aufgaben": ["Winkel a) in Grad", "Winkel b) in Grad", "Winkel c) in Grad"],
  loesung: ["Aufgabennummer", "Lösungstext"],
  erwartungshorizont: ["Aufgabe", "Erwartete Lösung"],
  bewertungsfelder: ["Gesamtpunktzahl"],
  abstand: ["Höhe mit Einheit (cm, mm oder pt)"],
  "zwei-spalten": ["Breite der linken Spalte in Prozent", "Linke Spalte", "Rechte Spalte"],
  "foerderplan-kopf": ["Name", "Klasse", "Schuljahr", "Lehrkraft", "Fach", "Datum"],
  karten: ["Überschrift", "Aufgabenstellung", "Karte A", "Karte B", "Karte C"],
  "kurs-editor-yaml": ["Dateiname", "Code"],
  "kurs-grading": ["Bewertungsmethode", "Frist (TT.MM.JJJJ; nur bei aktivierter Frist wirksam)"],
};

const PARAMETERS = {
  knoten: ["Zahlen am Rechenstrich", "Mit Kommas trennen; _ oder ? steht für ein leeres Kästchen."],
  spruenge: ["Sprünge", "Mit Kommas trennen, z. B. +13,+2 oder +_,+_."],
  zeilen: ["Zeilen", "1–12 Reihen."],
  spalten: ["Spalten", "1–20 Punkte pro Reihe."],
  oben: ["Obere Seitenabschnitte", "Teilzahlen mit Kommas trennen; beim Malkreuz 1–3, beim Flächenmodell 2."],
  links: ["Linke Seitenabschnitte", "Teilzahlen mit Kommas trennen; beim Malkreuz 1–3, beim Flächenmodell 2."],
  start: ["Starthöhe", "Zahl, optional mit Einheit, z. B. 1250 m."],
  etappen: ["Etappen", "1–5 Werte mit Kommas trennen; Vorzeichen und Einheit sind möglich."],
  offen: ["Ergebnisse offen lassen", "ja lässt Ergebnisse zum Ergänzen frei."],
  form: ["Dreiecksform", "Die Zeichnung ist schematisch; Beschriftungen sind frei wählbar."],
  drehung: ["Drehung in Grad", "Positive Winkel drehen gegen den Uhrzeigersinn."],
  markiert: ["Markierungen", "Seiten und Winkel mit Kommas trennen: a,b,c,alpha,beta,gamma."],
  a: ["Seite a", "Freie Beschriftung, z. B. a oder 7 cm."],
  beta: ["Winkel β", "Freie Beschriftung, z. B. β oder 14°."],
  alpha: ["Winkel α", "Freie Beschriftung, z. B. α oder 30°."],
  x: ["Waagerechte Strecke x", "Freie Beschriftung mit oder ohne Einheit."],
  h: ["Höhe h", "Freie Beschriftung mit oder ohne Einheit."],
  s: ["Schräge Strecke / Kante s", "Freie Beschriftung mit oder ohne Einheit."],
  laenge: ["Länge", "Freie Beschriftung mit oder ohne Einheit."],
  breite: ["Breite", "Freie Beschriftung mit oder ohne Einheit."],
  raeder: ["Anzahl der Räder", "1–6 Räder."],
  ziffern: ["Einstellungen pro Rad", "2–9 Einstellungen."],
  innen: ["Innenbeschriftung", "Leer lassen, um die Beschriftung wegzulassen."],
  spiele: ["Anzahl der Spiele", "1–14 Spiele."],
  zeichen: ["Tippzeichen", "2–4 Zeichen mit Kommas trennen, z. B. 1,0,2."],
};

const EXTRA_OPTIONS = {
  "modell-schriftlich": [["gruppen", "Teilprodukte farbig zuordnen", "Zeilenfarben passen zur zeilenweisen Gruppierung im Malkreuz.", ["", "keine", "zeilen"]],
    ["endnullen", "Endnullen ausschreiben", "ja füllt verschobene Teilprodukte rechts mit Nullen auf.", ["", "ja", "nein"]],
    ["teilrechnungen", "Teilrechnungen anzeigen", "ja schreibt neben jede Zeile, was dort gerechnet wird.", ["", "ja", "nein"]]],
  "modell-punktefeld": [["produkt", "Produkt anzeigen", "ja schreibt die Gesamtzahl der Punkte unter das Feld.", ["", "ja", "nein"]]],
  "modell-vierhundertfeld": [
    ["zeilen", "Zeilen des Rechtecks", "Zusammen mit spalten wird ein Rechteck oben links eingefärbt."],
    ["spalten", "Spalten des Rechtecks", "Zusammen mit zeilen wird ein Rechteck oben links eingefärbt."],
    ["zerlegung", "Zerlegung an der Zehnerstelle", "spalten zerlegt nur die Spalten, zeilen nur die Zeilen.", ["", "beide", "spalten", "zeilen"]],
    ["produkte", "Produkte der Teilflächen", "ja schreibt die Produkte in die Teilrechtecke.", ["", "ja", "nein"]],
    ["seite", "Seite markieren", "Klammer mit Anzahl der Zeilen bzw. Spalten.", ["", "zeilen", "spalten", "beide"]],
  ],
  "modell-rechenstrich": [["offen", "Sprünge ausblenden", "ja zeigt nur Strich und Knoten.", ["", "ja", "nein"]]],
  "modell-hoehenprofil-abstieg": [["summe", "Gesamtänderung", "Optionaler Bogen über alle Etappen, z. B. -1050."]],
  "modell-hoehenprofil-aufstieg": [["summe", "Gesamtänderung", "Optionaler Bogen über alle Etappen, z. B. +520 m."]],
  "skizze-dreieck": [["hoehe", "Höhe auf AB einzeichnen", "Optional die Höhe ergänzen.", ["", "ja", "nein"]]],
  "skizze-dreieck-gedreht": [["hoehe", "Höhe auf AB einzeichnen", "Optional die Höhe ergänzen.", ["", "ja", "nein"]]],
};

const NUMBER_RULES = {
  schreiblinien: [[1, 30]],
  einheitskreis: [[null, null, "any"]],
  "einheitskreis-aufgaben": [[null, null, "any"], [null, null, "any"], [null, null, "any"]],
  "skizze-zahlenschloss": [[1, 6], [2, 9]],
  "skizze-tippzettel": [[1, 14]],
  "modell-punktefeld": [[1, 12], [1, 20]],
  "zwei-spalten": [[1, 99, "any"]],
};

// Explicit field types keep catalogue wording independent of input behavior.
const MULTILINE_FIELDS = {
  "schuelerdialog-zwei": [2, 5],
  "schuelerdialog-farben": [4, 9],
  "schuelerdialog-drei": [2, 5, 8],
  "schuelerdialog-modelle": [2, 3, 6, 7],

  "wahr-falsch": [0], loesung: [1], erwartungshorizont: [1], hinweise: [0],
  infobox: [1], warnbox: [1], tippbox: [1], "zwei-spalten": [1, 2], "mini-ab": [0],
  karten: [1],
  "code-hinweis": [0], referenz: [0], versionen: [0, 1], foerderbereich: [1, 2],
  "kurs-warnbox": [1], "kurs-infobox": [1], "kurs-hinweisbox": [1], "kurs-tippbox": [1],
  "kurs-code-beispiel": [0], "kurs-code-noeditor": [0], "kurs-editor-startcode": [0],
  "kurs-editor-yaml": [1], "kurs-instructions": [0],
};
const CODE_SHORTCUTS = new Set(["kurs-code-beispiel", "kurs-code-noeditor", "kurs-editor-startcode"]);
const LENGTH_SHORTCUTS = new Set(["antwortlinie-breite", "antwortkasten", "platz", "eingabetabelle", "abstand"]);

export function shortcutFields(item) {
  const fields = [...item.code.matchAll(/\{\{(.*?)\}\}/g)].map((match, index) => {
    const parameter = item.code.slice(0, match.index).match(/\b(\w+)=\s*$/)?.[1];
    const [label, help = ""] = PARAMETERS[parameter] || [];
    const name = CODE_SHORTCUTS.has(item.id) ? "Python-Code" : LABELS[item.id]?.[index] || label || match[1];
    return {
      key: parameter || name,
      tagValue: Boolean(parameter),
      slot: index,
      value: match[1],
      label: name,
      help,
      type: MULTILINE_FIELDS[item.id]?.includes(index) ? "multiline" : "text",
      number: NUMBER_RULES[item.id]?.[index],
      choices: item.id.startsWith("schuelerdialog-") && /^Figur /.test(name) ? ["brille", "kurz", "locken", "zopf", "keine"]
        : parameter === "form" ? ["allgemein", "gleichschenklig", "recht-A", "recht-B", "recht-C", "stumpf-A", "stumpf-C"]
        : parameter === "offen" || parameter === "nullzeile" ? ["ja", "nein"] : null,
    };
  });
  for (const [parameter, label, help, choices] of EXTRA_OPTIONS[item.id] || []) {
    fields.push({ key: parameter, parameter, label, help, choices, value: "", type: "text" });
  }
  if (item.id === "schuelerfelder") fields.push({ key: "abstand", label: "Abstand nach oben", help: "Optionaler Abstand in cm, z. B. 1cm; leer für den Standard.", value: "", type: "text" });
  if (item.id === "kurs-grading") fields.push({ key: "enableDueDate", label: "Frist aktivieren", value: "false", choices: ["false", "true"] });
  if (item.id === "kurs-editor-yaml") {
    for (const [key, label] of [["visibleToLearner", "Für Lernende sichtbar"], ["learnerEditable", "Für Lernende bearbeitbar"]]) {
      fields.push({ key, label, value: "false", choices: ["false", "true"] });
    }
  }
  return fields;
}

export function configuredShortcut(item, fields, values) {
  const byKey = Object.fromEntries(fields.map((field, i) => [field.key, values[i]]));
  let index = 0;
  let code = item.code.replace(/\{\{(.*?)\}\}/g, () => {
    const slot = index++;
    let value = values[slot];
    if ((LENGTH_SHORTCUTS.has(item.id) || item.id === "rechengitter") && slot === 0) value = value.trim().replace(",", ".").replace(/\s+/g, "").replace(/^\./, "0.");
    if (item.id === "kurs-editor-yaml") {
      if (slot === 0) value = JSON.stringify(value);
      if (slot === 1) value = value.replace(/\r\n?/g, "\n").replace(/\n/g, "\n      ");
    }
    if (item.id === "kurs-grading" && slot === 1) value = JSON.stringify(value);
    return value;
  });
  const extras = fields.flatMap((field, i) => field.parameter && values[i].trim()
    ? [` | ${field.parameter}=${values[i].trim()}`] : []).join("");
  if (extras) code = code.replace(/(\[(?:Modell|Skizze) [^\]\n]*)(\])/, (_, start, end) => start + extras + end);
  // Offener Rechenstrich ohne Sprünge: den leeren Parameter weglassen.
  if (item.id === "modell-rechenstrich" && byKey.offen === "ja" && !byKey.spruenge.trim()) code = code.replace(/ \| spruenge=\s*\|/, " |");
  if (item.id === "schuelerfelder" && byKey.abstand.trim()) code = `[Schuelerfelder ${byKey.abstand.trim().replace(",", ".").replace(/\s+/g, "").replace(/^\./, "0.")}]`;
  for (const key of ["enableDueDate", "visibleToLearner", "learnerEditable"]) {
    const indent = key === "enableDueDate" ? "  " : "    ";
    if (byKey[key] !== undefined) code = code.replace(new RegExp(`^${indent}${key}: false$`, "m"), `${indent}${key}: ${byKey[key]}`);
  }
  return code;
}

export function shortcutErrors(item, fields, values) {
  const errors = fields.map(() => "");
  const set = (index, message) => { errors[index] ||= message; };
  const list = value => value.split(",").map(part => part.trim()).filter(Boolean);
  const length = /^(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?:cm|mm|pt)$/;
  fields.forEach((field, i) => {
    const value = values[i].trim();
    if (field.number) {
      const n = Number(value);
      const [min, max, step = 1] = field.number;
      if (!value || !Number.isFinite(n) || (step !== "any" && !Number.isInteger(n)) || (min != null && n < min) || (max != null && n > max)) {
        set(i, `Bitte eine ${step === "any" ? "Zahl" : "ganze Zahl"}${min != null ? ` ab ${min}` : ""}${max != null ? ` bis ${max}` : ""} eingeben.`);
      }
    }
    if (field.choices && !field.choices.includes(value)) set(i, "Bitte eine angebotene Option wählen.");
    if (item.id.startsWith("schuelerdialog-") && /^Name /.test(field.label) && (!value || /["\r\n]/.test(value))) set(i, "Namen ohne Anführungszeichen oder Zeilenumbrüche eingeben.");
    if (LENGTH_SHORTCUTS.has(item.id) && i === 0) {
      if (!length.test(value) || parseFloat(value.replace(",", ".")) <= 0) set(i, "Bitte eine positive Länge mit cm, mm oder pt eingeben, z. B. 1cm.");
    }
    if (item.id === "schuelerfelder" && value && !/^(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*cm$/.test(value)) {
      set(i, "Bitte einen nicht negativen Abstand in cm eingeben, z. B. 1cm.");
    }
    if ((field.parameter || field.tagValue) && /[|\]\r\n]/.test(value)) set(i, "Bitte ohne Zeilenumbrüche, | oder ] eingeben.");
  });
  if (item.id === "rechengitter") {
    const size = Number(values[0].replace(",", "."));
    if (!Number.isFinite(size) || size <= 0 || !/^\s*(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*$/.test(values[0])) set(0, "Bitte eine positive Kästchengröße in cm eingeben.");
    for (const i of [1, 2]) {
      if (i === 2 && !values[i].trim()) continue;
      if (!/^\d+$/.test(values[i].trim()) || Number(values[i]) < 1) set(i, "Bitte eine positive ganze Zahl eingeben.");
    }
  }
  if (item.id === "modell-rechenstrich") {
    const nodes = list(values[0]), jumps = list(values[1]);
    const open = values[fields.findIndex(field => field.key === "offen")] === "ja";
    if (nodes.length < 2 || nodes.length > (open ? 13 : 6)) set(0, `Bitte 2–${open ? 13 : 6} Zahlen oder Platzhalter mit Kommas trennen.`);
    if (jumps.length !== nodes.length - 1 && !(open && !jumps.length)) set(1, `Für ${nodes.length} Knoten werden ${Math.max(0, nodes.length - 1)} Sprünge benötigt${open ? "; alternativ das Feld leer lassen" : ""}.`);
  }
  if (item.id === "schuelerdialog-farben") {
    for (const i of [1, 2, 3, 6, 7, 8]) {
      if (!/^#[0-9a-fA-F]{6}$/.test(values[i])) set(i, "Sechsstelligen Hex-Farbcode eingeben, z. B. #498532.");
    }
  }
  if (item.id === "modell-schriftlich") {
    const factors = values[0].replace(/\s+/g, "").match(/^([0-9]{1,6})[*·×]([0-9]{1,6})$/);
    if (!factors || factors.slice(1).some(factor => factor.length > 1 && factor.startsWith("0"))) set(0, "Zwei natürliche Faktoren mit je 1–6 Ziffern ohne führende Nullen eingeben.");
    const width = values[2].trim().match(/^(\d+(?:\.\d+)?)mm$/);
    if (!width || Number(width[1]) < 10 || Number(width[1]) > 250) set(2, "Bildbreite zwischen 10mm und 250mm eingeben.");
  }
  if (item.id === "modell-ziffernraetsel") {
    const factors = values[0].replace(/\s+/g, "").match(/^([0-9_?]{1,6})\s*[*·×x]\s*([0-9_?]{1,6})$/);
    if (!factors || factors.slice(1).some(factor => factor.length > 1 && factor.startsWith("0"))) set(0, "Zwei Faktoren mit je 1–6 Ziffern oder Lücken eingeben, z. B. 3_1_*2; keine führenden Nullen.");
    if (!/^(?:0|[1-9][0-9]{0,11})$/.test(values[1].trim())) set(1, "Ergebnis mit 1–12 Ziffern ohne führende Nullen eingeben.");
    const width = values[2].trim().match(/^(\d+(?:\.\d+)?)mm$/);
    if (!width || Number(width[1]) < 10 || Number(width[1]) > 250) set(2, "Bildbreite zwischen 10mm und 250mm eingeben.");
  }
  if (item.id === "kurs-grading") {
    const active = values[fields.findIndex(field => field.key === "enableDueDate")] === "true";
    if (active) {
      const date = values[1].match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
      const parsed = date && new Date(Date.UTC(+date[3], +date[2] - 1, +date[1]));
      if (!date || parsed.getUTCFullYear() !== +date[3] || parsed.getUTCMonth() !== +date[2] - 1 || parsed.getUTCDate() !== +date[1]) set(1, "Bitte ein gültiges Datum als TT.MM.JJJJ eingeben.");
    }
  }
  return errors;
}

function fieldHtml(field, i, escapeHtml) {
  const attributes = `id="shortcut-field-${i}" aria-labelledby="shortcut-label-${i}" aria-describedby="shortcut-help-${i} shortcut-error-${i}"`;
  let control;
  if (field.choices) {
    control = `<select ${attributes}>${field.choices.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value === "true" ? "Ja" : value === "false" ? "Nein" : value || "Standard")}</option>`).join("")}</select>`;
  } else if (field.type === "multiline") {
    control = `<textarea ${attributes} rows="4" spellcheck="false"></textarea>`;
  } else {
    const [min, max, step = 1] = field.number || [];
    control = `<input ${attributes} type="${field.number ? "number" : "text"}" ${field.number ? `step="${step}" ${min != null ? `min="${min}"` : ""} ${max != null ? `max="${max}"` : ""}` : ""}>`;
  }
  return `<label for="shortcut-field-${i}"><span id="shortcut-label-${i}">${escapeHtml(field.label)}</span>${control}
    <small id="shortcut-help-${i}" class="shortcut-hint">${escapeHtml(field.help || "")}</small>
    <small id="shortcut-error-${i}" class="shortcut-field-error" aria-live="polite"></small></label>`;
}

export function showShortcutOptions({ item, body, escapeHtml, onBack, onInsert }) {
  const fields = shortcutFields(item);
  const storageKey = `material-ui:shortcut:${item.id}`;
  let saved;
  try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch { /* Storage is optional. */ }
  // Migrate the known original array schema; subsequent versions use field keys.
  const originalCount = fields.length - (item.id === "kurs-editor-yaml" ? 2 : item.id === "kurs-grading" ? 1 : 0);
  const legacy = Array.isArray(saved) && saved.length === originalCount && saved.every(value => typeof value === "string");
  const keyed = saved?.version === 2 && saved.values && !Array.isArray(saved.values);
  const previous = legacy || keyed ? fields.map((field, i) => {
    const value = legacy ? saved[i] : saved.values[field.key];
    return typeof value === "string" && (!field.choices || field.choices.includes(value)) ? value : field.value;
  }) : null;
  const form = document.createElement("form");
  form.className = "shortcut-settings";
  form.noValidate = true;
  form.innerHTML = `
    <div class="shortcut-settings-actions"><button type="button" data-action="back">← Zur Auswahl</button></div>
    <h2>${escapeHtml(item.label)}</h2>
    <p class="shortcut-hint">${escapeHtml(item.hint)}</p>
    <p>Die Felder sind mit ${previous ? "deinen zuletzt eingefügten Einstellungen" : "Beispielwerten"} vorbelegt. Passe sie vor dem Einfügen an.</p>
    <div class="shortcut-settings-actions">
      <button type="button" data-action="defaults">Beispielwerte verwenden</button>
      ${previous ? '<button type="button" data-action="previous">Letzte Einstellungen verwenden</button>' : ""}
    </div>
    <div class="shortcut-fields">${fields.map((field, i) => fieldHtml(field, i, escapeHtml)).join("")}</div>
    <details open><summary>Text, der eingefügt wird</summary><pre class="shortcut-code"></pre></details>
    <div class="shortcut-settings-actions"><button type="button" data-action="cancel">Abbrechen</button><button type="submit" class="primary">Einfügen</button></div>`;
  const inputs = fields.map((_, i) => form.querySelector(`#shortcut-field-${i}`));
  const values = () => inputs.map(input => input.value);
  let submitted = false;
  const update = () => {
    const entries = values();
    const errors = shortcutErrors(item, fields, entries);
    const enabled = fields.findIndex(field => field.key === "enableDueDate");
    if (enabled >= 0) inputs[1].disabled = entries[enabled] !== "true";
    inputs.forEach((input, i) => {
      input.setCustomValidity(errors[i]);
      input.setAttribute("aria-invalid", String(submitted && !!errors[i]));
      form.querySelector(`#shortcut-error-${i}`).textContent = submitted ? errors[i] : "";
    });
    form.querySelector("pre").textContent = configuredShortcut(item, fields, entries);
    return errors;
  };
  const fill = entries => {
    inputs.forEach((input, i) => { input.value = entries[i]; });
    submitted = false;
    update();
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.querySelector('[data-action="back"]').addEventListener("click", onBack);
  form.querySelector('[data-action="cancel"]').addEventListener("click", onBack);
  form.querySelector('[data-action="defaults"]').addEventListener("click", () => fill(fields.map(field => field.value)));
  form.querySelector('[data-action="previous"]')?.addEventListener("click", () => fill(previous));
  form.addEventListener("submit", event => {
    event.preventDefault();
    submitted = true;
    const errors = update();
    const invalid = errors.findIndex(Boolean);
    if (invalid >= 0) { inputs[invalid].focus(); return; }
    const entries = values();
    try { localStorage.setItem(storageKey, JSON.stringify({ version: 2, values: Object.fromEntries(fields.map((field, i) => [field.key, entries[i]])) })); } catch { /* Inserting also works without storage. */ }
    onInsert(configuredShortcut(item, fields, entries));
  });
  body.append(form);
  body.classList.add("configuring");
  fill(previous || fields.map(field => field.value));
  inputs.find(input => !input.disabled)?.focus();
  return () => { form.remove(); body.classList.remove("configuring"); };
}
