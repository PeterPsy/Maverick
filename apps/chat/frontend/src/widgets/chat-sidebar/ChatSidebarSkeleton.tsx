export function ChatSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="bs-chat-sidebar-skeleton">
      {Array.from({ length: 3 }).map((_, sectionIndex) => (
        <section className="bs-chat-sidebar-skeleton__section" key={sectionIndex}>
          <div className="bs-chat-sidebar-skeleton__header">
            <span className="bs-chat-sidebar-skeleton__line bs-chat-sidebar-skeleton__line--title" />
            <span className="bs-chat-sidebar-skeleton__chip" />
          </div>
          {Array.from({ length: sectionIndex === 0 ? 4 : 3 }).map((_, rowIndex) => (
            <div className="bs-chat-sidebar-skeleton__row" key={rowIndex}>
              <span className="bs-chat-sidebar-skeleton__line bs-chat-sidebar-skeleton__line--row" />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
