import { useState } from "react";
import { BACKGROUNDS } from "./slide-backgrounds";
import { belongsToSlide, solutionStep } from "./presentation-scene";

export function BackgroundPanel({ apply, insert }) {
  const [kind, setKind] = useState("grid");
  const [spacing, setSpacing] = useState(25);
  const [axisStep, setAxisStep] = useState(1);
  const valid = Number.isFinite(spacing) && spacing >= 10 && spacing <= 100
    && (!["coordinates", "number-line"].includes(kind) || Number.isFinite(axisStep) && axisStep >= .01 && axisStep <= 1000);
  return <>
    <strong>Mathematischer Hintergrund</strong>
    <label>Vorlage<select aria-label="Hintergrundvorlage" value={kind} onChange={(e) => setKind(e.target.value)}>{BACKGROUNDS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
    <label>Rasterabstand<input aria-label="Rasterabstand" type="number" min="10" max="100" step="5" value={spacing} onChange={(e) => setSpacing(+e.target.value)} /></label>
    {["coordinates", "number-line"].includes(kind) && <label>Wert je Kästchen<input aria-label="Achsenskalierung" type="number" min=".01" max="1000" step=".5" value={axisStep} onChange={(e) => setAxisStep(+e.target.value)} /></label>}
    {!valid && <small role="status">Rasterabstand: 10 bis 100. Achsenwert: 0,01 bis 1000.</small>}
    <button disabled={!valid} onClick={() => apply({ kind, spacing, axisStep })}>Auf aktuelle Folie anwenden</button>
    <button disabled={!valid} onClick={() => insert({ kind, spacing, axisStep })}>Neue Folie mit Vorlage</button>
  </>;
}
export function SolutionPanel({ api, frame, revealed, change, assign, revision }) {
  const elements = api.getSceneElements().filter((el) => belongsToSlide(el, frame));
  const steps = [...new Set(elements.map(solutionStep).filter(Boolean))].sort((a, b) => a - b);
  const selection = api.getAppState().selectedElementIds;
  const count = elements.filter((el) => selection[el.id] && el.type !== "frame" && !el.customData?.slideBackground).length;
  const [step, setStep] = useState(1);
  return <>
    <strong>Lösungsschritte</strong>
    <small>Ausgewählte Texte, Formen oder Bilder einem Schritt zuordnen. Zum Vorbereiten ggf. „Bearbeiten“ und den Hintergrund entsperren.</small>
    <label>Schritt<input type="number" aria-label="Lösungsschritt" min="1" max="100" value={step} onChange={(e) => setStep(Math.max(1, Math.min(100, +e.target.value || 1)))} /></label>
    <button disabled={!count} onClick={() => assign(step)}>Auswahl als Lösungsschritt markieren</button>
    <button disabled={!count} onClick={() => assign(0)}>Auswahl ist Aufgabeninhalt</button>
    <small>{count} ausgewählt · {steps.length} Lösungsschritte</small>
    <button onClick={() => change(0)}>Alle Lösungen verdecken</button>
    <button disabled={!steps.some((n) => n > revealed)} onClick={() => change(steps.find((n) => n > revealed) ?? revealed)}>Nächsten Lösungsschritt zeigen</button>
    <button disabled={!steps.length} onClick={() => change(steps.at(-1) ?? 0)}>Alle Lösungen zeigen</button>
    <span role="status">Sichtbar bis Schritt {revealed}</span>
  </>;
}
export function ExportPanel({ busy, exportPdf }) {
  return <><strong>Unterrichtsstand als PDF</strong><small>Eine Seite je Folie, einschließlich aller eigenen Anmerkungen. Lösungsschritte können gezielt ausgelassen werden.</small>
    <button disabled={!!busy} onClick={() => exportPdf(false)}>PDF nur mit Aufgaben</button>
    <button disabled={!!busy} onClick={() => exportPdf(true)}>PDF mit Lösungen</button>
    {busy && <span role="status">PDF wird erstellt: {busy}</span>}
  </>;
}
