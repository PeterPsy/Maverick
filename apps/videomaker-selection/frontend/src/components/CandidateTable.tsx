import { Check, ChevronRight, ExternalLink, Star } from 'lucide-react';
import { CALL_STATUSES, DECISIONS, EMAIL_STATUSES, POC_STATUSES, labelFor } from '../constants';
import type { Candidate } from '../types';

type Props = {
  candidates: Candidate[]; selectedIds: Set<string>; onSelect:(candidate:Candidate)=>void;
  onToggle:(id:string,checked:boolean)=>void; onUpdate:(id:string,payload:Partial<Candidate>)=>void; showRanking:boolean;
};
const score = (value:number|null) => value == null ? '—' : value.toFixed(1);
const validUrl = (value:string) => /^https?:\/\//i.test(value) ? value : `https://${value}`;
function PipelineSelect({value,items,onChange,label}:{value:string;items:Array<{value:string;label:string}>;onChange:(value:string)=>void;label:string}) {
  return <select aria-label={label} className={`pipeline-select status-${value}`} value={value} onClick={event=>event.stopPropagation()} onChange={event=>onChange(event.target.value)}>{items.map(item=><option key={item.value} value={item.value}>{item.label}</option>)}</select>;
}
export default function CandidateTable({candidates,selectedIds,onSelect,onToggle,onUpdate,showRanking}:Props) {
  return <>
    <div className="candidate-table-wrap"><table className="candidate-table">
      <thead><tr><th className="check-cell"><span className="sr-only">Seleziona</span></th><th>Candidato</th><th>Valutazione</th><th>Decisione</th><th>Email</th><th>Call</th><th>POC</th><th></th></tr></thead>
      <tbody>{candidates.map((candidate,index)=><tr key={candidate.id} className={selectedIds.has(candidate.id)?'is-checked':''} onClick={()=>onSelect(candidate)}>
        <td className="check-cell"><button aria-label={`Seleziona ${candidate.name}`} className={`check-box ${selectedIds.has(candidate.id)?'is-active':''}`} onClick={event=>{event.stopPropagation();onToggle(candidate.id,!selectedIds.has(candidate.id));}} type="button">{selectedIds.has(candidate.id)?<Check size={13}/>:null}</button></td>
        <td><div className="identity"><span className="avatar">{candidate.name.split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()}</span><div><strong>{candidate.name}</strong><small>{candidate.city || candidate.email}</small><span className="identity-meta">{candidate.profile_code || '—'}{candidate.specialty?` · ${candidate.specialty}`:''}</span></div>{candidate.favorite?<Star className="favorite-mark" size={13} fill="currentColor"/>:null}</div></td>
        <td><div className="score-cell"><strong>{score(candidate.review_score)}</strong><span>/ 10</span></div><small>{showRanking?`Pos. #${index+1} · `:''}Form {score(candidate.form_fit_score)}</small></td>
        <td><PipelineSelect label={`Decisione per ${candidate.name}`} value={candidate.decision} items={DECISIONS} onChange={value=>onUpdate(candidate.id,{decision:value as Candidate['decision']})}/></td>
        <td><PipelineSelect label={`Email per ${candidate.name}`} value={candidate.email_status} items={EMAIL_STATUSES} onChange={value=>onUpdate(candidate.id,{email_status:value as Candidate['email_status']})}/></td>
        <td><PipelineSelect label={`Call per ${candidate.name}`} value={candidate.call_status} items={CALL_STATUSES} onChange={value=>onUpdate(candidate.id,{call_status:value as Candidate['call_status']})}/></td>
        <td><PipelineSelect label={`POC per ${candidate.name}`} value={candidate.poc_status} items={POC_STATUSES} onChange={value=>onUpdate(candidate.id,{poc_status:value as Candidate['poc_status']})}/></td>
        <td><ChevronRight size={16} className="row-arrow"/></td>
      </tr>)}</tbody>
    </table></div>
    <div className="candidate-cards">{candidates.map(candidate=><article className="candidate-card" key={candidate.id} onClick={()=>onSelect(candidate)}>
      <div className="candidate-card-head"><span className="avatar">{candidate.name.split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()}</span><div><h3>{candidate.name}</h3><p>{candidate.city || candidate.email}</p></div><strong className="card-score">{score(candidate.review_score)}</strong></div>
      <p className="card-summary">{candidate.summary || candidate.annotation || candidate.bio || 'Profilo da completare'}</p>
      <div className="card-pipeline"><span className={`status-pill status-${candidate.decision}`}>{labelFor(DECISIONS,candidate.decision)}</span><span>{labelFor(EMAIL_STATUSES,candidate.email_status)}</span><span>{labelFor(CALL_STATUSES,candidate.call_status)}</span></div>
      <div className="card-actions"><button className={`check-box ${selectedIds.has(candidate.id)?'is-active':''}`} onClick={event=>{event.stopPropagation();onToggle(candidate.id,!selectedIds.has(candidate.id));}} type="button">{selectedIds.has(candidate.id)?<Check size={13}/>:null}</button>{candidate.portfolio_url?<a href={validUrl(candidate.portfolio_url)} onClick={event=>event.stopPropagation()} rel="noreferrer" target="_blank">Portfolio <ExternalLink size={12}/></a>:null}<ChevronRight size={16}/></div>
    </article>)}</div>
  </>;
}
