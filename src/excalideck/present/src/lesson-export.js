import { exportToCanvas, getCommonBounds } from "@excalidraw/excalidraw";
import { belongsToSlide, solutionStep } from "./presentation-scene";

export async function slideCanvas(elements, frame, files, appState, { solutions = true, size = 1600 } = {}) {
  const members = elements.filter((el) => !el.isDeleted && belongsToSlide(el, frame) && (solutions || !solutionStep(el)));
  // Zugeordnete Randnotizen erweitern die Exportseite, ohne den echten Frame
  // oder die Szene zu verändern. Originale Foliengrafiken bleiben beschnitten.
  let exportingFrame = frame.id === "__canvas__" ? null : frame;
  const annotations = members.filter((el) => el.customData?.annotationSlide === frame.id);
  if (exportingFrame && annotations.length) {
    const [left, top, right, bottom] = getCommonBounds(annotations);
    const padding = Math.max(2, ...annotations.map((el) => (el.strokeWidth || 0) / 2 + 2));
    const x = Math.min(frame.x, left - padding), y = Math.min(frame.y, top - padding);
    exportingFrame = { ...frame, x, y, width: Math.max(frame.x + frame.width, right + padding) - x,
      height: Math.max(frame.y + frame.height, bottom + padding) - y };
  }
  const expanded = exportingFrame && exportingFrame !== frame;
  // Den Originalrahmen zum Beschneiden der Aufgaben beibehalten. Nur eigene
  // Randnotizen werden in dieser Exportkopie vom Rahmen gelöst.
  const exportElements = expanded ? [
    ...members.map((el) => el.customData?.annotationSlide === frame.id ? { ...el, frameId: null } : el),
    { ...exportingFrame, id: `${frame.id}-export-bounds`, type: "rectangle", frameId: null,
      opacity: 0, strokeWidth: 0, strokeColor: "transparent", backgroundColor: "transparent", groupIds: [] },
  ] : members;
  return exportToCanvas({ elements: exportElements, files, exportingFrame: expanded ? null : exportingFrame,
    exportPadding: 0, maxWidthOrHeight: size,
    appState: { ...appState, exportBackground: true, viewBackgroundColor: "#ffffff", exportWithDarkMode: false,
      frameRendering: { enabled: true, name: false, outline: false, clip: true } },
  });
}
const ascii = (text) => new TextEncoder().encode(text);
export function makePdf(pages) {
  // Rasterexport ohne externe Dienste, Fonts oder zusaetzliche PDF-Abhaengigkeit.
  // Eine JPEG-XObject pro Seite, PDF-Offsets zaehlen Bytes statt JS-Zeichen.
  const objects = new Map();
  const kids = pages.map((_, i) => `${3 + i * 3} 0 R`).join(" ");
  objects.set(1, [ascii("<< /Type /Catalog /Pages 2 0 R >>")]);
  objects.set(2, [ascii(`<< /Type /Pages /Count ${pages.length} /Kids [${kids}] >>`)]);
  pages.forEach((page, i) => {
    const pageId = 3 + i * 3, imageId = pageId + 1, contentId = pageId + 2;
    const width = 842, height = Number((842 * page.height / page.width).toFixed(3));
    const commands = ascii(`q ${width} 0 0 ${height} 0 0 cm /Image${i} Do Q`);
    objects.set(pageId, [ascii(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /XObject << /Image${i} ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`)]);
    objects.set(imageId, [ascii(`<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.jpeg.length} >>\nstream\n`), page.jpeg, ascii("\nendstream")]);
    objects.set(contentId, [ascii(`<< /Length ${commands.length} >>\nstream\n`), commands, ascii("\nendstream")]);
  });
  const chunks = [ascii("%PDF-1.4\n%excalideck\n")];
  const offsets = [0];
  let length = chunks[0].length;
  for (let id = 1; id <= objects.size; id++) {
    offsets[id] = length;
    const parts = [ascii(`${id} 0 obj\n`), ...objects.get(id), ascii("\nendobj\n")];
    for (const part of parts) { chunks.push(part); length += part.length; }
  }
  const start = length;
  chunks.push(ascii(`xref\n0 ${objects.size + 1}\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size ${objects.size + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`));
  return new Blob(chunks, { type: "application/pdf" });
}
export async function exportLesson({ elements, slides, files, appState, solutions, name, progress }) {
  const pages = [];
  for (const [i, frame] of slides.entries()) {
    progress?.(`${i + 1} / ${slides.length}`);
    const canvas = await slideCanvas(elements, frame, files, appState, { solutions, size: 2400 });
    const data = atob(canvas.toDataURL("image/jpeg", .94).split(",")[1]);
    pages.push({ width: canvas.width, height: canvas.height, jpeg: Uint8Array.from(data, (char) => char.charCodeAt(0)) });
    canvas.width = canvas.height = 0;
  }
  const blob = makePdf(pages);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(name || "Folien").replace(/\.excalidraw$/i, "")}${solutions ? "-mit-loesungen" : "-aufgaben"}.pdf`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
