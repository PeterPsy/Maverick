interface ChecklistAppSkeletonProps {
  viewMode: 'board' | 'detail';
}

const BOARD_CARD_COUNT = 4;
const DETAIL_PLAN_ROW_COUNT = 5;
const WIDGET_PLAN_ROW_COUNT = 3;

export function ChecklistAppSkeleton({ viewMode }: ChecklistAppSkeletonProps) {
  if (viewMode === 'detail') {
    return <ChecklistDetailSkeleton />;
  }
  return <ChecklistBoardSkeleton />;
}

export function ChecklistWidgetSkeleton() {
  return (
    <article
      className="checklist-widget-card checklist-widget-skeleton"
      role="status"
      aria-label="Checklist content is loading"
    >
      <header className="checklist-widget-card__header" aria-hidden="true">
        <span className="checklist-widget-skeleton__title-block">
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--kicker" />
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--widget-title" />
        </span>
        <span className="checklist-loading-skeleton__counter" />
      </header>
      <PlanSkeleton compact rowCount={WIDGET_PLAN_ROW_COUNT} />
    </article>
  );
}

function ChecklistBoardSkeleton() {
  return (
    <section
      className="checklist-plans-view checklist-loading-skeleton"
      role="status"
      aria-label="Checklist plans are loading"
    >
      <header className="detail-header checklist-loading-skeleton__header" aria-hidden="true">
        <div className="detail-title-block">
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--title" />
          <span className="detail-title-separator" />
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--subtitle" />
        </div>
      </header>
      <div className="checklist-plans-grid checklist-loading-skeleton__grid" aria-hidden="true">
        {Array.from({ length: BOARD_CARD_COUNT }).map((_, index) => (
          <article className="checklist-plan-card checklist-loading-skeleton__card" key={index}>
            <header className="checklist-plan-card__header">
              <span className="checklist-loading-skeleton__title-stack">
                <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--kicker" />
                <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--card-title" />
                <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--card-copy" />
              </span>
              <span className="checklist-loading-skeleton__button" />
            </header>
            <span className="checklist-loading-skeleton__meta">
              <span />
              <span />
              <span />
            </span>
            <div className="checklist-plan-card__body checklist-loading-skeleton__task-preview">
              <span className="checklist-loading-skeleton__task-block" />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ChecklistDetailSkeleton() {
  return (
    <section
      className="checklist-loading-skeleton checklist-detail-skeleton"
      role="status"
      aria-label="Checklist is loading"
    >
      <header className="detail-header checklist-loading-skeleton__header" aria-hidden="true">
        <div className="detail-title-block">
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--title" />
          <span className="detail-title-separator" />
          <span className="checklist-loading-skeleton__line checklist-loading-skeleton__line--subtitle" />
        </div>
      </header>
      <div className="checklist-detail-board checklist-loading-skeleton__detail-board" aria-hidden="true">
        <PlanSkeleton rowCount={DETAIL_PLAN_ROW_COUNT} />
      </div>
    </section>
  );
}

function PlanSkeleton({ compact = false, rowCount }: { compact?: boolean; rowCount: number }) {
  return (
    <div className={`checklist-plan-skeleton ${compact ? 'is-compact' : ''}`}>
      <div className="checklist-plan-skeleton__card">
        <div className="checklist-plan-skeleton__inner">
          {Array.from({ length: rowCount }).map((_, index) => (
            <SkeletonPlanRow compact={compact} key={index} short={index === rowCount - 1} />
          ))}
        </div>
      </div>
    </div>
  );
}

function SkeletonPlanRow({ compact = false, short = false }: { compact?: boolean; short?: boolean }) {
  return (
    <div className={`checklist-plan-skeleton__row ${compact ? 'is-compact' : ''}`}>
      <span className="checklist-plan-skeleton__icon" />
      <span className="checklist-plan-skeleton__copy">
        <span
          className={`checklist-loading-skeleton__line ${
            short ? 'checklist-loading-skeleton__line--plan-short' : 'checklist-loading-skeleton__line--plan'
          }`}
        />
      </span>
      {!compact ? <span className="checklist-plan-skeleton__pill" /> : null}
    </div>
  );
}
