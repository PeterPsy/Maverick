import { AtSign, ExternalLink, FolderOpen, PlayCircle } from 'lucide-react';
import { extractLinks, instagramHandle, instagramLinks, linkLabel, linkPreview, portfolioLinks } from '../links';
import type { Candidate } from '../types';

function LinkCard({ href, title, subtitle }: { href: string; title: string; subtitle: string }) {
  return <a className="asset-link" href={href} target="_blank" rel="noreferrer">
    <span><strong>{title}</strong><small>{subtitle}</small></span><ExternalLink aria-hidden="true" size={15}/>
  </a>;
}

export default function CandidateAssets({ candidate }: { candidate: Candidate }) {
  const portfolios = portfolioLinks(candidate);
  const profiles = instagramLinks(candidate);
  const tests = extractLinks(candidate.test_url || '');
  return <section className="drawer-section candidate-assets">
    <h3>Portfolio e link</h3>
    <div className="asset-group">
      <div className="asset-group-heading"><span className="asset-icon"><FolderOpen size={16}/></span><div><h4>Link portfolio</h4><p>{portfolios.length ? `${portfolios.length} ${portfolios.length === 1 ? 'link disponibile' : 'link disponibili'}` : 'Nessun link indicato'}</p></div></div>
      {portfolios.length ? <div className="asset-link-list">{portfolios.map((url, index)=><LinkCard key={url} href={url} title={`${linkLabel(url)}${portfolios.length > 1 ? ` ${index + 1}` : ''}`} subtitle={linkPreview(url)}/>)}</div> : <p className="asset-empty">Il candidato non ha fornito un portfolio.</p>}
    </div>
    {profiles.length ? <div className="asset-group instagram-group">
      <div className="asset-group-heading"><span className="asset-icon"><AtSign size={16}/></span><div><h4>Profilo Instagram</h4><p>{profiles.length === 1 ? 'Profilo individuato nella candidatura' : `${profiles.length} profili individuati nella candidatura`}</p></div></div>
      <div className="asset-link-list">{profiles.map(url=><LinkCard key={url} href={url} title={instagramHandle(url)} subtitle="Apri il profilo Instagram"/>)}</div>
    </div> : null}
    <div className="asset-group test-group">
      <div className="asset-group-heading"><span className="asset-icon"><PlayCircle size={16}/></span><div><h4>Prova video</h4><p>{tests.length ? `${tests.length} ${tests.length === 1 ? 'link disponibile' : 'link disponibili'}` : 'Nessun link indicato'}</p></div></div>
      {tests.length ? <div className="asset-link-list">{tests.map((url,index)=><LinkCard key={url} href={url} title={tests.length > 1 ? `Prova video ${index + 1}` : 'Apri la prova video'} subtitle={linkPreview(url)}/>)}</div> : null}
    </div>
  </section>;
}
