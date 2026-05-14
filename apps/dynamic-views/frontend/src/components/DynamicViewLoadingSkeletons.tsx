const APP_META_PILL_COUNT = 2;
const FRAME_CARD_COUNT = 3;
const FRAME_ROW_COUNT = 4;
const WIDGET_META_PILL_COUNT = 3;

export function DynamicViewAppSkeleton() {
  return (
    <section className="dv-loading-skeleton" role="status" aria-label="Dynamic views are loading">
      <header className="detail-header dv-loading-skeleton__header" aria-hidden="true">
        <div className="detail-title-block">
          <span className="dv-loading-skeleton__line dv-loading-skeleton__line--title" />
          <span className="detail-title-separator" />
          <span className="dv-loading-skeleton__line dv-loading-skeleton__line--subtitle" />
        </div>
        <span className="dv-loading-skeleton__meta">
          {Array.from({ length: APP_META_PILL_COUNT }).map((_, index) => (
            <span className="dv-loading-skeleton__pill" key={index} />
          ))}
        </span>
      </header>

      <section className="dv-layout dv-viewer-layout" aria-hidden="true">
        <section className="dv-preview dv-card-panel dv-loading-skeleton__panel" aria-label="Dynamic view preview">
          <div className="dv-section-head">
            <span className="dv-loading-skeleton__title-stack">
              <span className="dv-loading-skeleton__line dv-loading-skeleton__line--kicker" />
              <span className="dv-loading-skeleton__line dv-loading-skeleton__line--panel-title" />
            </span>
            <span className="dv-loading-skeleton__icon-button" />
          </div>
          <DynamicViewFrameSkeleton />
        </section>
      </section>
    </section>
  );
}

export function DynamicViewWidgetSkeleton() {
  return (
    <main className="dv-widget dv-widget-skeleton" role="status" aria-label="Dynamic view is loading">
      <header className="dv-widget__head" aria-hidden="true">
        <span className="dv-widget-skeleton__icon" />
        <span className="dv-widget-skeleton__title">
          <span className="dv-loading-skeleton__line dv-loading-skeleton__line--widget-kicker" />
          <span className="dv-loading-skeleton__line dv-loading-skeleton__line--widget-title" />
          <span className="dv-loading-skeleton__line dv-loading-skeleton__line--widget-copy" />
        </span>
        <span className="dv-widget-skeleton__button" />
      </header>
      <DynamicViewFrameSkeleton compact />
      <footer className="dv-widget__meta dv-widget-skeleton__meta" aria-hidden="true">
        {Array.from({ length: WIDGET_META_PILL_COUNT }).map((_, index) => (
          <span className="dv-loading-skeleton__pill" key={index} />
        ))}
      </footer>
    </main>
  );
}

function DynamicViewFrameSkeleton({ compact = false }: { compact?: boolean }) {
  const cardCount = compact ? 2 : FRAME_CARD_COUNT;
  const rowCount = compact ? 3 : FRAME_ROW_COUNT;

  return (
    <div className={`dv-frame-skeleton ${compact ? 'is-compact' : ''}`}>
      <div className="dv-frame-skeleton__toolbar">
        <span className="dv-frame-skeleton__chip" />
        <span className="dv-frame-skeleton__chip is-short" />
      </div>
      <div className="dv-frame-skeleton__hero">
        <span className="dv-frame-skeleton__line dv-frame-skeleton__line--title" />
        <span className="dv-frame-skeleton__line dv-frame-skeleton__line--copy" />
      </div>
      <div className="dv-frame-skeleton__cards">
        {Array.from({ length: cardCount }).map((_, index) => (
          <span className="dv-frame-skeleton__card" key={index} />
        ))}
      </div>
      <div className="dv-frame-skeleton__rows">
        {Array.from({ length: rowCount }).map((_, index) => (
          <span className={`dv-frame-skeleton__row ${index === rowCount - 1 ? 'is-short' : ''}`} key={index} />
        ))}
      </div>
    </div>
  );
}
