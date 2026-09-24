/** Reading layout only: chronology orders rows, graph depth separates columns. */
/* Card size and the grid it sits on, kept together so the stylesheet, the positions and
   the edge endpoints cannot drift apart. The gaps are what is left over after the card.

   A card is only as tall as what is in it, up to `height`; a one-line title should not
   leave a band of empty card under it. Because heights vary, edges meet the card at a
   fixed distance from its top — beside the title, where the eye already is — rather than
   at a midpoint that would sit near the bottom of a short card. */
export const NODE = {width: 240, height: 90, anchor: 32, pitchX: 300, pitchY: 110};

export function dateKey(node) {
  const value = node.date?.slice(0, 10);
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(value + 'T00:00:00Z');
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}
export function layoutComponent(component) {
  const byId = new Map(component.nodes.map(n => [n.id, n]));
  const indegree = new Map(component.nodes.map(n => [n.id, 0]));
  const children = new Map(component.nodes.map(n => [n.id, []]));
  const depth = new Map(component.nodes.map(n => [n.id, 0]));
  component.edges.forEach(e => {children.get(e.parent).push(e.child); indegree.set(e.child, indegree.get(e.child) + 1);});
  const ready = component.nodes.filter(n => !indegree.get(n.id)).map(n => n.id);
  for (let index = 0; index < ready.length; index++) {
    const id = ready[index];
    children.get(id).forEach(child => {
      depth.set(child, Math.max(depth.get(child), depth.get(id) + 1));
      indegree.set(child, indegree.get(child) - 1);
      if (!indegree.get(child)) ready.push(child);
    });
  }
  const sorted = [...byId.values()].sort((a,b) =>
    (dateKey(a) || '9999').localeCompare(dateKey(b) || '9999') || depth.get(a.id) - depth.get(b.id) || a.id.localeCompare(b.id));
  const positions = new Map(sorted.map((node, i) => [node.id, {x:170 + depth.get(node.id) * NODE.pitchX, y:72 + i * NODE.pitchY, depth:depth.get(node.id)}]));
  return {
    nodes: sorted,
    positions,
    width: Math.max(760, 170 + NODE.width + 48 + Math.max(0,...depth.values()) * NODE.pitchX),
    height: Math.max(300, 96 + sorted.length * NODE.pitchY),
  };
}
export function edgePath(left, right) {
  const x1 = left.x + NODE.width, y1 = left.y + NODE.anchor, x2 = right.x, y2 = right.y + NODE.anchor;
  const bend = Math.max(30, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}`;
}
