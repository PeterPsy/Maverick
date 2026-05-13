export type GraphPhysicsNode = {
  id: string;
  vx: number;
  vy: number;
  x: number;
  y: number;
};

const EXACT_REPULSION_NODE_LIMIT = 180;
const GRID_CELL_SIZE = 180;

export function applyRepulsion<TNode extends GraphPhysicsNode>(nodes: TNode[]) {
  if (nodes.length <= EXACT_REPULSION_NODE_LIMIT) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        applyRepulsionPair(nodes[i], nodes[j]);
      }
    }
    return;
  }
  applyGridRepulsion(nodes);
}

function applyGridRepulsion<TNode extends GraphPhysicsNode>(nodes: TNode[]) {
  const grid = new Map<string, TNode[]>();
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  nodes.forEach((node) => {
    const key = gridKey(node.x, node.y);
    const cell = grid.get(key);
    if (cell) {
      cell.push(node);
    } else {
      grid.set(key, [node]);
    }
  });

  nodes.forEach((node, index) => {
    const cellX = Math.floor(node.x / GRID_CELL_SIZE);
    const cellY = Math.floor(node.y / GRID_CELL_SIZE);
    for (let x = cellX - 1; x <= cellX + 1; x += 1) {
      for (let y = cellY - 1; y <= cellY + 1; y += 1) {
        const cell = grid.get(`${x}:${y}`);
        if (!cell) continue;
        cell.forEach((other) => {
          if ((indexById.get(other.id) ?? -1) <= index) return;
          applyRepulsionPair(node, other);
        });
      }
    }
  });
}

function applyRepulsionPair(a: GraphPhysicsNode, b: GraphPhysicsNode) {
  const dx = b.x - a.x || 0.01;
  const dy = b.y - a.y || 0.01;
  const distance = Math.max(20, Math.hypot(dx, dy));
  const force = 900 / (distance * distance);
  const fx = (dx / distance) * force;
  const fy = (dy / distance) * force;
  a.vx -= fx;
  a.vy -= fy;
  b.vx += fx;
  b.vy += fy;
}

function gridKey(x: number, y: number) {
  return `${Math.floor(x / GRID_CELL_SIZE)}:${Math.floor(y / GRID_CELL_SIZE)}`;
}
