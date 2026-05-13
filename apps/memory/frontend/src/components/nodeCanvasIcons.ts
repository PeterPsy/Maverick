import { iconNodeForType, type NodeIconElement } from "./nodeIcons";

const pathCache = new Map<string, Path2D>();

export function drawNodeIcon(
  ctx: CanvasRenderingContext2D,
  type: string,
  x: number,
  y: number,
  radius: number,
  color: string,
) {
  const size = Math.max(12, Math.min(22, radius * 0.92));
  const scale = size / 24;

  ctx.save();
  ctx.translate(x - size / 2, y - size / 2);
  ctx.scale(scale, scale);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  iconNodeForType(type).forEach((element) => drawIconElement(ctx, element));

  ctx.restore();
}

function drawIconElement(ctx: CanvasRenderingContext2D, [tag, attrs]: NodeIconElement) {
  if (tag === "path" && typeof attrs.d === "string") {
    const path = cachedPath(attrs.d);
    if (attrs.fill === "currentColor") {
      ctx.fill(path);
    } else {
      ctx.stroke(path);
    }
    return;
  }

  if (tag === "circle") {
    const cx = numberAttr(attrs.cx);
    const cy = numberAttr(attrs.cy);
    const radius = numberAttr(attrs.r);
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    if (attrs.fill === "currentColor") {
      ctx.fill();
    } else {
      ctx.stroke();
    }
    return;
  }

  if (tag === "rect") {
    const x = numberAttr(attrs.x);
    const y = numberAttr(attrs.y);
    const width = numberAttr(attrs.width);
    const height = numberAttr(attrs.height);
    const radius = numberAttr(attrs.rx);
    ctx.beginPath();
    if ("roundRect" in ctx && radius > 0) {
      ctx.roundRect(x, y, width, height, radius);
    } else {
      ctx.rect(x, y, width, height);
    }
    if (attrs.fill === "currentColor") {
      ctx.fill();
    } else {
      ctx.stroke();
    }
  }
}

function cachedPath(definition: string): Path2D {
  const cached = pathCache.get(definition);
  if (cached) return cached;
  const path = new Path2D(definition);
  pathCache.set(definition, path);
  return path;
}

function numberAttr(value: string | number | undefined): number {
  if (typeof value === "number") return value;
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}
