import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { Candidate } from '../types';
type Props={open:boolean;onClose:()=>void;onCreate:(payload:Partial<Candidate>)=>Promise<void>};
export default function NewCandidateDialog({open,onClose,onCreate}:Props){
 const [form,setForm]=useState({name:'',email:'',city:'',portfolio_url:''}); const [saving,setSaving]=useState(false);
 if(!open)return null;
 const submit=async(e:React.FormEvent)=>{e.preventDefault();if(!form.name.trim())return;setSaving(true);try{await onCreate(form);setForm({name:'',email:'',city:'',portfolio_url:''});onClose()}finally{setSaving(false)}};
 return <div className="dialog-layer" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><form className="new-dialog" onSubmit={submit}><header><div><p className="eyebrow">Nuovo profilo</p><h2>Aggiungi candidato</h2></div><button className="icon-button" onClick={onClose} type="button"><X size={18}/></button></header><label>Nome e cognome<input autoFocus required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label><label>Città<input value={form.city} onChange={e=>setForm({...form,city:e.target.value})}/></label><label>Portfolio<input placeholder="https://" value={form.portfolio_url} onChange={e=>setForm({...form,portfolio_url:e.target.value})}/></label><footer><button className="secondary-button" onClick={onClose} type="button">Annulla</button><button className="primary-button" disabled={saving} type="submit"><Plus size={16}/>{saving?'Creo…':'Crea candidato'}</button></footer></form></div>
}
