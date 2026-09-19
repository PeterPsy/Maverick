import { ExternalLink, Link2 } from 'lucide-react';
import { Provider, useLiveCrm } from '../domain/vnext';

export function IntegrationsView() {
  const result = useLiveCrm<{ providers: Provider[] }>({ action: 'crm.integration_context' });
  return <section className="vn-page"><header className="vn-page-heading"><div><small>CONNECTED WORKSPACE</small><h1>Apps & connections</h1><p>Your CRM connects through Maverick interfaces. Existing provider selections and record links stay in place.</p></div></header>
    {result.error ? <p className="crm-alert" role="alert">{result.error}</p> : null}
    <div className="vn-card-grid">{result.data?.providers.map((provider) => <section className="vn-surface" key={provider.alias}><span className="vn-card-kicker"><Link2 size={17} />{provider.configured ? 'Provider selected' : 'Not configured'}</span><h2>{provider.interface}</h2><p className="vn-hint">{provider.selected_provider_app_ids.join(', ') || 'Select an optional provider in workspace Settings.'}</p><p>{provider.linked_count} linked records</p>
      {provider.configured ? <a href={`/app/${encodeURIComponent(provider.selected_provider_app_ids[0])}`} target="_top">Open provider <ExternalLink size={14} /></a> : null}
    </section>)}</div>
    <section className="vn-surface"><h2>Clear ownership, explicit actions</h2><p className="vn-hint">Mail owns email and drafts. Calendar owns events. Storage owns files and audio. Speech owns transcription. Checklist owns external task boards. CRM stores the relationship and business context, not their private data or credentials.</p><p className="vn-hint">Search and verify provider records from a CRM detail page. Verified links refresh in bounded background batches; freshness and failures remain visible. Existing unverified snapshots are preserved until you explicitly refresh them.</p><p className="vn-hint">Prepare drafts, native calendar meetings, documents, Checklist tasks and transcriptions, then approve and execute separately. Sending remains in Mail. Meeting outcomes produce reviewable follow-ups. Campaign automation is excluded.</p></section>
  </section>;
}
