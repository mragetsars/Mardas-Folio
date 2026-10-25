/** Interpolate source anchors, preserving approximate place across reflow. */
export function interpolatePosition(anchors, value, from = "line", to = "top") {
  if (!anchors.length) return 0;
  const sorted = [...anchors].sort((a, b) => a[from] - b[from]);
  let previous = sorted[0];
  if (value <= previous[from]) return previous[to];
  for (const next of sorted.slice(1)) {
    if (value <= next[from]) {
      const span = next[from] - previous[from];
      return span > 0 ? previous[to] + (next[to] - previous[to]) * (value - previous[from]) / span : next[to];
    }
    previous = next;
  }
  return previous[to];
}
