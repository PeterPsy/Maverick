export function SkillsDetailSkeleton() {
  return (
    <div className="skills-detail-skeleton" role="status" aria-label="Loading skills">
      <header className="detail-header skills-detail-skeleton__header" aria-hidden="true">
        <span className="skills-detail-skeleton__line skills-detail-skeleton__line--title" />
        <span className="skills-detail-skeleton__line skills-detail-skeleton__line--subtitle" />
        <span className="skills-detail-skeleton__actions">
          <span />
          <span />
        </span>
      </header>
      <div className="skill-bento-grid skills-detail-skeleton__grid" aria-hidden="true">
        <section className="bento-card bento-card-skill skills-detail-skeleton__card">
          <span className="skills-detail-skeleton__line skills-detail-skeleton__line--small" />
          <span className="skills-detail-skeleton__field" />
          <span className="skills-detail-skeleton__field skills-detail-skeleton__field--tall" />
          <span className="skills-detail-skeleton__bars" />
        </section>
        <section className="bento-card bento-card-origin skills-detail-skeleton__card">
          <span className="skills-detail-skeleton__line skills-detail-skeleton__line--medium" />
          <span className="skills-detail-skeleton__rows" />
        </section>
        <section className="bento-card bento-card-identity skills-detail-skeleton__card">
          <span className="skills-detail-skeleton__line skills-detail-skeleton__line--short" />
          <span className="skills-detail-skeleton__rows" />
        </section>
        <section className="bento-card bento-card-instructions skills-detail-skeleton__card">
          <span className="skills-detail-skeleton__line skills-detail-skeleton__line--medium" />
          <span className="skills-detail-skeleton__field skills-detail-skeleton__field--fill" />
        </section>
        <section className="bento-card bento-card-preview skills-detail-skeleton__card">
          <span className="skills-detail-skeleton__line skills-detail-skeleton__line--medium" />
          <span className="skills-detail-skeleton__field skills-detail-skeleton__field--fill" />
        </section>
      </div>
    </div>
  );
}
