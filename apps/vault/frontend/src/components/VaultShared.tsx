import React from 'react';

export function Stat({ active = false, icon, label, muted, onClick, value }: {
  active?: boolean;
  icon: React.ReactNode;
  label: string;
  muted?: string;
  onClick?: () => void;
  value: string;
}) {
  return (
    <button className={`vault-stat ${active ? 'is-active' : ''}`} onClick={onClick} type="button">
      <span className="vault-stat__icon">{icon}</span>
      <strong>{value}</strong>
      <small>{label}</small>
      {muted ? <em>{muted}</em> : null}
    </button>
  );
}

export function PanelHeader({ caption, icon, title }: { caption: string; icon: React.ReactNode; title: string }) {
  return (
    <div className="vault-panel-header">
      <div>
        <h2>{icon}{title}</h2>
        <p>{caption}</p>
      </div>
    </div>
  );
}

export function DataPanel({ caption = 'Redacted operational inventory.', children, count, title }: {
  caption?: string;
  children: React.ReactNode;
  count: number;
  title: string;
}) {
  return (
    <section className="vault-table-wrap">
      <div className="vault-panel-header">
        <div>
          <h2>{title}</h2>
          <p>{caption}</p>
        </div>
        <span>{count} items</span>
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ title }: { title: string }) {
  return <div className="vault-empty">{title}</div>;
}

export function Status({ value }: { value: string }) {
  return <span className={`vault-status is-${value}`}>{value}</span>;
}
