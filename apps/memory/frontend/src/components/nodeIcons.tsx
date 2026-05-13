import { createElement, type SVGProps } from "react";

export type NodeIconElement = [string, Record<string, string | number>];
export type NodeIconNode = NodeIconElement[];

const fallbackIcon: NodeIconNode = [
  [
    "path",
    {
      d: "M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z",
      key: "brain-left",
    },
  ],
  ["path", { d: "M9 13a4.5 4.5 0 0 0 3-4", key: "brain-curve" }],
  ["path", { d: "M12 13h4", key: "brain-link-a" }],
  ["path", { d: "M12 18h6a2 2 0 0 1 2 2v1", key: "brain-link-b" }],
  ["path", { d: "M12 8h8", key: "brain-link-c" }],
  ["circle", { cx: "16", cy: "13", r: ".5", key: "brain-dot-a" }],
  ["circle", { cx: "20", cy: "21", r: ".5", key: "brain-dot-b" }],
  ["circle", { cx: "20", cy: "8", r: ".5", key: "brain-dot-c" }],
];

export const nodeTypeIconNodes: Record<string, NodeIconNode> = {
  note: [
    [
      "path",
      {
        d: "M21 9a2.4 2.4 0 0 0-.706-1.706l-3.588-3.588A2.4 2.4 0 0 0 15 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2z",
        key: "sticky-note-page",
      },
    ],
    ["path", { d: "M15 3v5a1 1 0 0 0 1 1h5", key: "sticky-note-fold" }],
  ],
  fact: [
    [
      "path",
      {
        d: "M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z",
        key: "badge",
      },
    ],
    ["path", { d: "m9 12 2 2 4-4", key: "badge-check" }],
  ],
  decision: [
    ["circle", { cx: "12", cy: "18", r: "3", key: "fork-bottom" }],
    ["circle", { cx: "6", cy: "6", r: "3", key: "fork-left" }],
    ["circle", { cx: "18", cy: "6", r: "3", key: "fork-right" }],
    ["path", { d: "M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9", key: "fork-join" }],
    ["path", { d: "M12 12v3", key: "fork-stem" }],
  ],
  file_ref: [
    [
      "path",
      {
        d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
        key: "file-page",
      },
    ],
    ["path", { d: "M14 2v5a1 1 0 0 0 1 1h5", key: "file-fold" }],
    ["path", { d: "M10 9H8", key: "file-line-a" }],
    ["path", { d: "M16 13H8", key: "file-line-b" }],
    ["path", { d: "M16 17H8", key: "file-line-c" }],
  ],
  app_entity_ref: [
    [
      "path",
      {
        d: "M10 22V7a1 1 0 0 0-1-1H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5a1 1 0 0 0-1-1H2",
        key: "blocks-base",
      },
    ],
    ["rect", { x: "14", y: "2", width: "8", height: "8", rx: "1", key: "blocks-top" }],
  ],
  person_ref: [
    ["path", { d: "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", key: "user-body" }],
    ["circle", { cx: "12", cy: "7", r: "4", key: "user-head" }],
  ],
  company_ref: [
    ["path", { d: "M10 12h4", key: "building-line-a" }],
    ["path", { d: "M10 8h4", key: "building-line-b" }],
    ["path", { d: "M14 21v-3a2 2 0 0 0-4 0v3", key: "building-door" }],
    [
      "path",
      {
        d: "M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2",
        key: "building-side",
      },
    ],
    ["path", { d: "M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16", key: "building-main" }],
  ],
  project_ref: [
    [
      "path",
      {
        d: "M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1",
        key: "folder",
      },
    ],
    ["path", { d: "M2 13h10", key: "folder-arrow-line" }],
    ["path", { d: "m9 16 3-3-3-3", key: "folder-arrow" }],
  ],
  topic: [
    [
      "path",
      {
        d: "M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z",
        key: "tag-body",
      },
    ],
    ["circle", { cx: "7.5", cy: "7.5", r: ".5", fill: "currentColor", key: "tag-dot" }],
  ],
  question: [
    ["circle", { cx: "12", cy: "12", r: "10", key: "question-circle" }],
    ["path", { d: "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3", key: "question-mark" }],
    ["path", { d: "M12 17h.01", key: "question-dot" }],
  ],
};

export function iconNodeForType(type: string): NodeIconNode {
  return nodeTypeIconNodes[type] || fallbackIcon;
}

type NodeTypeIconProps = SVGProps<SVGSVGElement> & {
  size?: number;
  type: string;
};

export function NodeTypeIcon({ size = 17, type, ...props }: NodeTypeIconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      viewBox="0 0 24 24"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      {iconNodeForType(type).map(([tag, attrs], index) => {
        const { key, ...elementAttrs } = attrs;
        return createElement(tag, { ...elementAttrs, key: key || index });
      })}
    </svg>
  );
}
