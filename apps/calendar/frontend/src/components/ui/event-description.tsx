import { Fragment, type ReactNode } from "react";
import { safeLink } from "./event-editor-domain";
function links(text: string): ReactNode[] {
  return text.split(/(https?:\/\/[^\s<>]+)/g).map((part, index) =>
    safeLink(part) ? (
      <a
        key={index}
        href={safeLink(part)}
        target="_blank"
        rel="noopener noreferrer"
      >
        {part}
      </a>
    ) : (
      part
    ),
  );
}
export function EventDescription({ text }: { text: string }) {
  if (!/<\/?[a-z][^>]*>/i.test(text) || typeof DOMParser === "undefined")
    return <div className="calendar-event-description">{links(text)}</div>;
  const document = new DOMParser().parseFromString(text, "text/html");
  function render(node: Node, key: string, insideLink = false): ReactNode {
    if (node.nodeType === 3)
      return (
        <Fragment key={key}>
          {insideLink ? node.textContent : links(node.textContent || "")}
        </Fragment>
      );
    if (node.nodeType !== 1) return null;
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (
      [
        "script",
        "style",
        "iframe",
        "object",
        "svg",
        "img",
        "input",
        "button",
      ].includes(tag)
    )
      return null;
    const children = Array.from(element.childNodes).map((child, index) =>
      render(child, `${key}-${index}`, insideLink || tag === "a"),
    );
    if (tag === "a") {
      const href = safeLink(element.getAttribute("href"));
      return href ? (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ) : (
        <Fragment key={key}>{children}</Fragment>
      );
    }
    if (tag === "br") return <br key={key} />;
    if (["strong", "b"].includes(tag))
      return <strong key={key}>{children}</strong>;
    if (["em", "i"].includes(tag)) return <em key={key}>{children}</em>;
    if (["p", "div"].includes(tag)) return <p key={key}>{children}</p>;
    if (tag === "ul") return <ul key={key}>{children}</ul>;
    if (tag === "ol") return <ol key={key}>{children}</ol>;
    if (tag === "li") return <li key={key}>{children}</li>;
    return <Fragment key={key}>{children}</Fragment>;
  }
  return (
    <div className="calendar-event-description">
      {Array.from(document.body.childNodes).map((node, index) =>
        render(node, String(index)),
      )}
    </div>
  );
}
