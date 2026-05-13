import type { CSSProperties } from "react";

type SkeletonNode = {
  id: string;
  size: number;
  x: number;
  y: number;
};

type SkeletonLink = {
  id: string;
  source: string;
  target: string;
};

type SkeletonNodeStyle = CSSProperties & {
  "--memory-skeleton-size": string;
  "--memory-skeleton-x": string;
  "--memory-skeleton-y": string;
};

export const memoryMapSkeletonNodes: SkeletonNode[] = [
  { id: "core-context", x: 50, y: 49, size: 48 },
  { id: "active-project", x: 35, y: 35, size: 34 },
  { id: "decision-trail", x: 66, y: 34, size: 38 },
  { id: "reference-file", x: 27, y: 59, size: 29 },
  { id: "user-signal", x: 73, y: 58, size: 31 },
  { id: "topic-cluster", x: 47, y: 70, size: 27 },
  { id: "question-thread", x: 59, y: 77, size: 24 },
];

export const memoryMapSkeletonLinks: SkeletonLink[] = [
  { id: "core-active-project", source: "core-context", target: "active-project" },
  { id: "core-decision-trail", source: "core-context", target: "decision-trail" },
  { id: "core-reference-file", source: "core-context", target: "reference-file" },
  { id: "core-user-signal", source: "core-context", target: "user-signal" },
  { id: "core-topic-cluster", source: "core-context", target: "topic-cluster" },
  { id: "topic-question-thread", source: "topic-cluster", target: "question-thread" },
  { id: "decision-user-signal", source: "decision-trail", target: "user-signal" },
];

export function MemoryMapSkeleton({ loading }: { loading: boolean }) {
  const nodeById = new Map(memoryMapSkeletonNodes.map((node) => [node.id, node]));

  return (
    <div aria-hidden="true" className="memory-map-skeleton" data-loading={loading ? "true" : "false"}>
      <svg className="memory-map-skeleton__links" focusable="false" viewBox="0 0 100 100" preserveAspectRatio="none">
        {memoryMapSkeletonLinks.map((link) => {
          const source = nodeById.get(link.source);
          const target = nodeById.get(link.target);
          if (!source || !target) return null;
          return (
            <line
              className="memory-map-skeleton__link"
              key={link.id}
              x1={source.x}
              x2={target.x}
              y1={source.y}
              y2={target.y}
            />
          );
        })}
      </svg>
      {memoryMapSkeletonNodes.map((node, index) => (
        <span
          className="memory-map-skeleton__node"
          key={node.id}
          style={{
            "--memory-skeleton-size": `${node.size}px`,
            "--memory-skeleton-x": `${node.x}%`,
            "--memory-skeleton-y": `${node.y}%`,
            animationDelay: `${index * 120}ms`,
          } as SkeletonNodeStyle}
        />
      ))}
    </div>
  );
}
