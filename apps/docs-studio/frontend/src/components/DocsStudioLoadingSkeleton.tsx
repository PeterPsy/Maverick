const BODY_LINE_COUNT = 7;
const CALLOUT_LINE_COUNT = 3;

export function DocsStudioLoadingSkeleton() {
  return (
    <main className="docs-app docs-loading-skeleton" role="status" aria-label="Docs Studio content is loading">
      <article className="doc-page" aria-hidden="true">
        <header className="doc-header docs-loading-skeleton__header">
          <div className="doc-title-block">
            <span className="docs-loading-skeleton__line docs-loading-skeleton__line--eyebrow" />
            <span className="docs-loading-skeleton__line docs-loading-skeleton__line--title" />
            <span className="doc-title-separator" />
            <span className="docs-loading-skeleton__line docs-loading-skeleton__line--lead" />
          </div>
        </header>

        <section className="markdown-preview docs-loading-skeleton__body">
          <span className="docs-loading-skeleton__line docs-loading-skeleton__line--heading" />
          <div className="docs-loading-skeleton__paragraph">
            {Array.from({ length: BODY_LINE_COUNT }).map((_, index) => (
              <span
                className={`docs-loading-skeleton__line ${
                  index === BODY_LINE_COUNT - 1
                    ? 'docs-loading-skeleton__line--body-short'
                    : 'docs-loading-skeleton__line--body'
                }`}
                key={index}
              />
            ))}
          </div>
          <div className="docs-loading-skeleton__callout">
            {Array.from({ length: CALLOUT_LINE_COUNT }).map((_, index) => (
              <span
                className={`docs-loading-skeleton__line ${
                  index === CALLOUT_LINE_COUNT - 1
                    ? 'docs-loading-skeleton__line--callout-short'
                    : 'docs-loading-skeleton__line--callout'
                }`}
                key={index}
              />
            ))}
          </div>
        </section>
      </article>
    </main>
  );
}
