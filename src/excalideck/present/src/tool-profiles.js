import { useRef } from "react";
const KEY = "excalideck:tool-profiles-v1";
const defaults = {
  pen: { strokeColor: "#1e1e1e", strokeWidth: 2, opacity: 100, strokeStyle: "solid", roughness: 1 },
  marker: { strokeColor: "#f08c00", strokeWidth: 16, opacity: 35, strokeStyle: "solid", roughness: 0 },
  shapes: { strokeColor: "#1e1e1e", strokeWidth: 2, opacity: 100, strokeStyle: "solid", roughness: 1 },
  text: { strokeColor: "#1e1e1e", strokeWidth: 2, opacity: 100, strokeStyle: "solid", roughness: 0 },
};
export const profileKey = (tool, marker) => tool === "freedraw" ? marker ? "marker" : "pen"
  : ["rectangle", "ellipse", "diamond", "line", "arrow"].includes(tool) ? "shapes" : tool === "text" ? "text" : null;
export function profileState(profile, zoom = 1) {
  return Object.fromEntries(Object.entries(profile).map(([key, value]) => [`currentItem${key[0].toUpperCase()}${key.slice(1)}`, key === "strokeWidth" ? value / zoom : value]));
}
const clean = (value, fallback) => ({
  strokeColor: /^#[\da-f]{6}$/i.test(value?.strokeColor) ? value.strokeColor : fallback.strokeColor,
  strokeWidth: Math.max(.5, Math.min(50, Number(value?.strokeWidth) || fallback.strokeWidth)),
  opacity: Number.isFinite(value?.opacity) ? Math.max(0, Math.min(100, value.opacity)) : fallback.opacity,
  strokeStyle: ["solid", "dashed", "dotted"].includes(value?.strokeStyle) ? value.strokeStyle : fallback.strokeStyle,
  roughness: [0, 1, 2].includes(value?.roughness) ? value.roughness : fallback.roughness,
});
export function useToolProfiles() {
  const ref = useRef(null);
  if (!ref.current) {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY)) ?? {}; } catch { /* Voreinstellungen ohne Storage */ }
    const profiles = Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, clean(saved[key], value)]));
    const favorites = [defaults.pen, { ...defaults.pen, strokeColor: "#e03131" }, { ...defaults.pen, strokeColor: "#1971c2", strokeWidth: 4 }]
      .map((fallback, i) => clean(saved.favorites?.[i], fallback));
    const persist = () => { try { localStorage.setItem(KEY, JSON.stringify({ ...profiles, favorites })); } catch { /* optional */ } };
    ref.current = { profiles, favorites,
      update(key, patch) {
        const next = clean({ ...profiles[key], ...patch }, defaults[key]);
        if (JSON.stringify(next) !== JSON.stringify(profiles[key])) { profiles[key] = next; persist(); }
      },
      favorite(index) { favorites[index] = { ...profiles.pen }; persist(); },
    };
  }
  return ref.current;
}
