import type { ReactNode } from "react";

const shapes: Record<string, ReactNode> = {
  instagram: <><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r=".7" fill="currentColor" stroke="none"/></>,
  twitter: <><path d="m4 3 12 18h4L8 3H4Z"/><path d="M20 3 4 21"/></>,
  reddit: <><ellipse cx="12" cy="14" rx="8" ry="6"/><path d="m12 8 2-5 5 1M8 17c2 1.5 6 1.5 8 0"/><circle cx="20" cy="4" r="2"/><path d="M8 12h.01M16 12h.01" strokeWidth="3"/></>,
  facebook: <path d="M14 21v-8h3l.5-4H14V7c0-1.5.5-2 2-2h2V2h-3c-3 0-5 2-5 5v2H7v4h3v8"/>,
  linkedin: <><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M7 10v7M7 7h.01M11 17v-7m0 3c0-4 6-4 6 0v4"/></>,
  youtube: <><rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3Z"/></>,
  rss: <><path d="M4 4a16 16 0 0 1 16 16M4 10a10 10 0 0 1 10 10"/><circle cx="5" cy="19" r="1" fill="currentColor"/></>,
  web: <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/></>,
  github: <><path d="M9 19c-4.3 1.3-4.3-2.5-6-3m12 6v-4c0-1 .1-1.5-.5-2 3.3-.4 6.5-1.6 6.5-7a5.5 5.5 0 0 0-1.5-3.8 5 5 0 0 0-.1-3.8S18.2 1 15.5 3a13 13 0 0 0-7 0C5.8 1 4.6 1.4 4.6 1.4a5 5 0 0 0-.1 3.8A5.5 5.5 0 0 0 3 9c0 5.4 3.2 6.6 6.5 7-.6.5-.5 1.1-.5 2v4"/></>,
};

export function SourceIcon({ source }: { source: string }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{shapes[source] || shapes.web}</svg>;
}
