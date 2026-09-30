export function Avatar({ name }: { name: string }) {
  const initials = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toLocaleUpperCase("it");
  return (
    <span aria-hidden="true" className="contact-avatar">
      {initials || "·"}
    </span>
  );
}
