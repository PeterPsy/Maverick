type ShellIconName = "apps" | "chevron-left" | "chevron-right" | "help" | "menu" | "plus" | "settings";

const PATHS: Record<ShellIconName, string[]> = {
  apps: [
    "M5 5h5v5H5z",
    "M14 5h5v5h-5z",
    "M5 14h5v5H5z",
    "M14 14h5v5h-5z",
  ],
  "chevron-left": ["M14.5 5.5 8 12l6.5 6.5"],
  "chevron-right": ["M9.5 5.5 16 12l-6.5 6.5"],
  help: [
    "M9.5 9a2.7 2.7 0 1 1 4.7 1.8c-.9.8-2.1 1.3-2.1 3",
    "M12 18h.01",
    "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z",
  ],
  menu: ["M5 7h14", "M5 12h14", "M5 17h14"],
  plus: ["M12 5v14", "M5 12h14"],
  settings: [
    "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z",
    "M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 3.4-.2-.1a1.7 1.7 0 0 0-1.9.1 8 8 0 0 1-1.4.8 1.7 1.7 0 0 0-1.1 1.5v.3H9v-.3a1.7 1.7 0 0 0-1.1-1.5 8 8 0 0 1-1.4-.8 1.7 1.7 0 0 0-1.9-.1l-.2.1-2-3.4.1-.1A1.7 1.7 0 0 0 2.8 15 7.7 7.7 0 0 1 2.6 12c0-.5.1-1 .2-1.5a1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-3.4.2.1a1.7 1.7 0 0 0 1.9-.1c.4-.3.9-.6 1.4-.8A1.7 1.7 0 0 0 9 2.8v-.3h4v.3a1.7 1.7 0 0 0 1.1 1.5c.5.2 1 .5 1.4.8a1.7 1.7 0 0 0 1.9.1l.2-.1 2 3.4-.1.1a1.7 1.7 0 0 0-.3 1.9c.1.5.2 1 .2 1.5s-.1 1-.2 1.5z",
  ],
};

export function ShellIcon({ name }: { name: ShellIconName }) {
  return (
    <svg aria-hidden="true" className="bs-shell-icon" fill="none" focusable="false" viewBox="0 0 24 24">
      {PATHS[name].map((path) => (
        <path d={path} key={path} />
      ))}
    </svg>
  );
}
