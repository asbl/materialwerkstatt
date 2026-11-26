import { useLayoutEffect, useState } from "react";

const size = 44;
const gap = 8;

// Möglichst nah an der Geometriehilfe bleiben, ohne Menüs oder Bildschirmränder
// zu überdecken. Die Zeichenhilfe selbst bleibt dabei an ihrer Szenenposition.
export function useGuideHandlePosition(left, top, reservedPosition = null) {
  const [position, setPosition] = useState({ left, top });
  useLayoutEffect(() => {
    const obstacles = [...document.querySelectorAll(".deck-geometry-controls, .deck-toolbar, .deck-lesson-tools, .deck-overview, .deck-zoom, .deck-guide-handle")];
    const place = () => {
      const maxX = Math.max(gap, innerWidth - size - gap);
      const maxY = Math.max(gap, innerHeight - size - gap);
      const clampX = x => Math.max(gap, Math.min(x, maxX));
      const clampY = y => Math.max(gap, Math.min(y, maxY));
      const boxes = obstacles.map(el => el.getBoundingClientRect()).filter(b => b.width && b.height);
      // Die berechnete Position reservieren, nicht den möglicherweise noch alten DOM-Stand.
      if (reservedPosition) boxes.push({ left: reservedPosition.left, top: reservedPosition.top,
        right: reservedPosition.left + size, bottom: reservedPosition.top + size });
      const xs = [clampX(left), gap, maxX, ...boxes.flatMap(b => [clampX(b.left - size - gap), clampX(b.right + gap)])];
      const ys = [clampY(top), gap, maxY, ...boxes.flatMap(b => [clampY(b.top - size - gap), clampY(b.bottom + gap)])];
      const candidates = xs.flatMap(x => ys.map(y => ({ left: x, top: y })));
      const overlaps = p => boxes.some(b => p.left < b.right + gap && p.left + size > b.left - gap && p.top < b.bottom + gap && p.top + size > b.top - gap);
      candidates.sort((a, b) => Math.hypot(a.left - left, a.top - top) - Math.hypot(b.left - left, b.top - top));
      const next = candidates.find(p => !overlaps(p)) ?? { left: clampX(left), top: clampY(top) };
      setPosition(old => old.left === next.left && old.top === next.top ? old : next);
    };
    place();
    const observer = new ResizeObserver(place);
    obstacles.forEach(el => observer.observe(el));
    window.addEventListener("resize", place);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); };
  }, [left, top, reservedPosition?.left, reservedPosition?.top]);
  return position;
}
