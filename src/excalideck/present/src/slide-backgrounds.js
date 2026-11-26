export const BACKGROUNDS = [
  ["blank", "Leer"], ["grid", "Rechenkästchen"], ["dots", "Punktepapier"],
  ["ruled", "Liniert"], ["coordinates", "Koordinatensystem"], ["number-line", "Zahlengerade"],
];
export function paperElements(frame, kind = "blank", spacing = 25, axisStep = 1) {
  spacing = Math.max(10, Math.min(100, Number(spacing) || 25));
  axisStep = Math.max(.01, Math.min(1000, Number(axisStep) || 1));
  const { x, y, width, height, id } = frame;
  const style = { frameId: id, locked: true, roughness: 0, strokeWidth: 1,
    strokeColor: "#cbd5e1", opacity: 100, customData: { slideBackground: true } };
  const result = [];
  const add = (element) => result.push({ ...style, id: crypto.randomUUID(), ...element });
  add({ type: "rectangle", x, y, width, height, strokeColor: "transparent", backgroundColor: "#ffffff", fillStyle: "solid" });
  const line = (left, top, dx, dy, extra = {}) => add({ type: "line", x: left, y: top, width: Math.abs(dx), height: Math.abs(dy), points: [[0, 0], [dx, dy]], ...extra });
  if (["grid", "coordinates"].includes(kind)) {
    for (let dx = spacing; dx < width; dx += spacing) line(x + dx, y, 0, height);
    for (let dy = spacing; dy < height; dy += spacing) line(x, y + dy, width, 0);
  }
  if (kind === "ruled") for (let dy = spacing; dy < height; dy += spacing) line(x, y + dy, width, 0);
  if (kind === "dots") {
    add({ type: "image", x, y, width, height, fileId: dotFileId(frame, spacing), status: "saved", scale: [1, 1], crop: null });
  }
  if (["coordinates", "number-line"].includes(kind)) {
    const cx = x + Math.floor(width / (2 * spacing)) * spacing;
    const cy = y + Math.floor(height / (2 * spacing)) * spacing;
    const axis = { strokeColor: "#334155", strokeWidth: 2, endArrowhead: "arrow", type: "arrow" };
    line(x + spacing, cy, width - 2 * spacing, 0, axis);
    if (kind === "coordinates") line(cx, y + height - spacing, 0, -height + 2 * spacing, axis);
    const label = (left, top, text) => add({ type: "text", x: left, y: top, text, originalText: text,
      fontSize: Math.max(12, Math.min(18, spacing / 2)), fontFamily: 2, strokeColor: "#334155" });
    for (let dx = spacing; dx < width - spacing; dx += spacing) {
      line(x + dx, cy - 4, 0, 8, { strokeColor: "#334155" });
      if (Math.round((x + dx - cx) / spacing) % 2 === 0) label(x + dx + 3, cy + 8, String(Number(((x + dx - cx) / spacing * axisStep).toFixed(4))));
    }
    if (kind === "coordinates") for (let dy = spacing; dy < height - spacing; dy += spacing) {
      line(cx - 4, y + dy, 8, 0, { strokeColor: "#334155" });
      const n = Math.round((cy - y - dy) / spacing);
      if (n && n % 2 === 0) label(cx + 8, y + dy, String(Number((n * axisStep).toFixed(4))));
    }
  }
  return result;
}

const dotFileId = (frame, spacing) => `paper-dots-${frame.width}-${frame.height}-${spacing}`;
export function paperFiles(frame, kind, spacing = 25) {
  if (kind !== "dots") return [];
  spacing = Math.max(10, Math.min(100, Number(spacing) || 25));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${frame.width}" height="${frame.height}"><defs><pattern id="dots" width="${spacing}" height="${spacing}" patternUnits="userSpaceOnUse"><circle cx="${spacing / 2}" cy="${spacing / 2}" r="1" fill="#94a3b8"/></pattern></defs><rect width="100%" height="100%" fill="url(#dots)"/></svg>`;
  return [{ id: dotFileId(frame, spacing), mimeType: "image/svg+xml", dataURL: `data:image/svg+xml;base64,${btoa(svg)}`, created: Date.now() }];
}
