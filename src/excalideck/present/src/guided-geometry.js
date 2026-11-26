export const rotatePoint = ([x, y], angle, origin) => {
  const a = angle * Math.PI / 180;
  return [origin.x + x * Math.cos(a) - y * Math.sin(a), origin.y + x * Math.sin(a) + y * Math.cos(a)];
};
export function projectToEdge(point, start, end) {
  const dx = end[0] - start[0], dy = end[1] - start[1];
  const t = Math.max(0, Math.min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy || 1)));
  return [start[0] + t * dx, start[1] + t * dy];
}
export function arcPoints(center, radius, start, sweep) {
  sweep = Math.max(-2 * Math.PI, Math.min(2 * Math.PI, sweep));
  const count = Math.max(2, Math.ceil(Math.abs(sweep) * 90 / Math.PI));
  return Array.from({ length: count + 1 }, (_, i) => [center.x + radius * Math.cos(start + sweep * i / count), center.y + radius * Math.sin(start + sweep * i / count)]);
}
export const angleDelta = (previous, next) => Math.atan2(Math.sin(next - previous), Math.cos(next - previous));
export const lineSkeleton = (points, style) => ({ type: "line", x: points[0][0], y: points[0][1],
  points: points.map(([x, y]) => [x - points[0][0], y - points[0][1]]), roughness: 0, ...style });
