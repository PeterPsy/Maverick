import { useEffect, useRef, type ReactNode } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, Search, X, type LucideIcon } from "lucide-react";
import "./dashboard-sidebar.css";

export type NavItemData = {
  id: string;
  title: string;
  icon: LucideIcon;
  badge?: number | string;
  description?: string;
};

export type NavGroupData = {
  heading: string;
  items: NavItemData[];
};

// App-owned data and actions replace the preview's mock workspaces and pages.
export function SidebarNav({
  groups,
  activeId,
  onSelect,
  searchQuery,
  onSearchChange,
  children,
}: {
  groups: NavGroupData[];
  activeId: string;
  onSelect: (id: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  children: ReactNode;
}) {
  const searchRef = useRef<HTMLInputElement>(null);
  const activeItem =
    groups
      .flatMap((group) => group.items)
      .find((item) => item.id === activeId) ?? groups[0]?.items[0];
  const ActiveIcon = activeItem?.icon;

  useEffect(() => {
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    }
    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, []);

  return (
    <div className="dashboard-sidebar flex min-h-0 flex-1 flex-col">
      <div className="dashboard-sidebar__toolbar">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              aria-label="Choose chat view"
              className="dashboard-sidebar__switcher"
              type="button"
            >
              <span className="dashboard-sidebar__avatar">
                {ActiveIcon ? <ActiveIcon size={18} strokeWidth={1.5} /> : null}
              </span>
              <span className="dashboard-sidebar__switcher-copy min-w-0 flex-1 text-left">
                <span className="dashboard-sidebar__eyebrow">Chat</span>
                <span className="dashboard-sidebar__switcher-title truncate">
                  {activeItem?.title}
                </span>
              </span>
              <span className="dashboard-sidebar__badge">
                {activeItem?.badge ?? 0}
              </span>
              <ChevronDown
                className="dashboard-sidebar__switcher-chevron"
                size={14}
              />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="start"
              className="dashboard-sidebar__menu"
              collisionPadding={8}
              sideOffset={6}
            >
              <DropdownMenu.RadioGroup
                onValueChange={onSelect}
                value={activeId}
              >
                {groups.map((group, index) => (
                  <DropdownMenu.Group key={group.heading}>
                    {index > 0 ? (
                      <DropdownMenu.Separator className="dashboard-sidebar__separator" />
                    ) : null}
                    <DropdownMenu.Label className="dashboard-sidebar__menu-heading">
                      {group.heading}
                    </DropdownMenu.Label>
                    {group.items.map((item) => (
                      <DropdownMenu.RadioItem
                        className="dashboard-sidebar__menu-item"
                        key={item.id}
                        value={item.id}
                      >
                        <item.icon
                          aria-hidden="true"
                          size={16}
                          strokeWidth={1.5}
                        />
                        <span className="dashboard-sidebar__menu-copy min-w-0 flex-1">
                          <span className="truncate">{item.title}</span>
                          {item.description ? (
                            <span className="dashboard-sidebar__description">
                              {item.description}
                            </span>
                          ) : null}
                        </span>
                        {item.badge !== undefined ? (
                          <span className="dashboard-sidebar__badge">
                            {item.badge}
                          </span>
                        ) : null}
                        <span className="dashboard-sidebar__check">
                          <DropdownMenu.ItemIndicator>
                            <Check size={14} />
                          </DropdownMenu.ItemIndicator>
                        </span>
                      </DropdownMenu.RadioItem>
                    ))}
                  </DropdownMenu.Group>
                ))}
              </DropdownMenu.RadioGroup>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
        <div className="bs-chat-sidebar-search-frame">
          <Search aria-hidden="true" size={16} />
          <input
            aria-label="Search chats"
            className="bs-chat-sidebar-search"
            onChange={(event) => onSearchChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onSearchChange("");
            }}
            placeholder="Search chats and messages"
            ref={searchRef}
            value={searchQuery}
          />
          {searchQuery ? (
            <button
              aria-label="Clear chat search"
              className="dashboard-sidebar__icon-button"
              onClick={() => {
                onSearchChange("");
                searchRef.current?.focus();
              }}
              type="button"
            >
              <X size={14} />
            </button>
          ) : (
            <kbd className="dashboard-sidebar__shortcut">⌘/Ctrl K</kbd>
          )}
        </div>
      </div>
      {children}
    </div>
  );
}

export function SidebarActionMenu({
  label,
  items,
  disabled = false,
  icon: Icon,
}: {
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
  items: Array<{
    title: string;
    icon: LucideIcon;
    onSelect: () => void;
    danger?: boolean;
  }>;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          aria-label={label}
          className="dashboard-sidebar__icon-button"
          disabled={disabled}
          type="button"
        >
          <Icon aria-hidden="true" size={16} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          className="dashboard-sidebar__menu dashboard-sidebar__menu--actions"
          collisionPadding={8}
          sideOffset={4}
        >
          {items.map((item) => (
            <DropdownMenu.Item
              className={`dashboard-sidebar__menu-item ${item.danger ? "is-danger" : ""}`}
              key={item.title}
              onSelect={item.onSelect}
            >
              <item.icon aria-hidden="true" size={15} />
              <span>{item.title}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function SidebarDisclosure({
  open,
  id,
  children,
}: {
  open: boolean;
  id: string;
  children: ReactNode;
}) {
  return (
    <div
      aria-hidden={!open}
      className="dashboard-sidebar__disclosure"
      data-open={open}
      id={id}
      inert={!open}
    >
      <div className="dashboard-sidebar__disclosure-inner">{children}</div>
    </div>
  );
}
