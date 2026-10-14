import { Icon } from "../Icon";
import { createAction, SECTIONS } from "../navigation";
import type { ViewId } from "../types";

type NavigationProps = { view: ViewId; navigate: (view: ViewId) => void };

export function SectionNavigation({
  view,
  navigate,
  mobile = false,
}: NavigationProps & { mobile?: boolean }) {
  return (
    <nav className={mobile ? "mobile-nav" : "desktop-nav"} aria-label="Sezioni">
      {SECTIONS.map(({ id, label, icon }) => (
        <button
          aria-current={view === id ? "page" : undefined}
          className={view === id ? "is-active" : ""}
          key={id}
          onClick={() => navigate(id)}
          type="button"
        >
          <Icon name={icon} size={mobile ? 18 : 16} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

export function AppTopbar({
  view,
  navigate,
  embedded,
  query,
  setQuery,
  disabled,
  onCreate,
}: NavigationProps & {
  embedded: boolean;
  query: string;
  setQuery: (query: string) => void;
  disabled: boolean;
  onCreate: () => void;
}) {
  const action = createAction(view);
  const searchLabel =
    view === "deliveries"
      ? "Cerca consegne"
      : view === "contacts"
        ? "Cerca contatti"
        : view === "tasks"
          ? "Cerca attività"
          : view === "ideas"
            ? "Cerca idee"
            : "Cerca lavori";
  return (
    <header className="app-topbar">
      {embedded ? (
        <span className="app-section-title">
          {SECTIONS.find((section) => section.id === view)?.label}
        </span>
      ) : (
        <button
          aria-label="Marta Ops"
          className="brand"
          onClick={() => navigate("today")}
          type="button"
        >
          <span className="brand-mark">
            <Icon name="board" size={18} />
          </span>
          <span>Marta Ops</span>
        </button>
      )}
      {!embedded && <SectionNavigation view={view} navigate={navigate} />}
      <div className="topbar-actions">
        <label className="app-search">
          <Icon name="search" size={17} />
          <input
            aria-label={searchLabel}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={searchLabel}
            value={query}
          />
        </label>
        <button
          aria-label={action.label}
          className="primary-action new-work"
          disabled={disabled}
          onClick={onCreate}
          type="button"
        >
          <Icon name="plus" size={17} />
          <span>{action.label}</span>
        </button>
      </div>
    </header>
  );
}
