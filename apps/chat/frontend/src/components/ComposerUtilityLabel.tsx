/** Labels shown when toolbar controls move into the compact utility panel. */
export function ComposerUtilityLabel({ label, detail, chevron = false }: { label: string; detail?: string; chevron?: boolean }) {
  return (
    <>
      <span aria-hidden="true" className="chatapp-composer-utilities__copy">
        <span className="chatapp-composer-utilities__label">{label}</span>
        {detail ? <span className="chatapp-composer-utilities__detail">{detail}</span> : null}
      </span>
      {chevron ? <span aria-hidden="true" className="chatapp-composer-utilities__chevron material-symbols-rounded">chevron_right</span> : null}
    </>
  );
}
