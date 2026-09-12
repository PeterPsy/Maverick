import type { CallStatus, Decision, EmailStatus, PocStatus } from './types';
export const DECISIONS: Array<{value:Decision;label:string}> = [
  {value:'da_valutare',label:'Da valutare'}, {value:'scartato',label:'Scartato'},
  {value:'riserva',label:'Scartato con riserva'}, {value:'selezionato',label:'Selezionato'}
];
export const EMAIL_STATUSES: Array<{value:EmailStatus;label:string}> = [
  {value:'da_contattare',label:'Da contattare'}, {value:'email_inviata',label:'Email inviata'},
  {value:'risposta_ricevuta',label:'Risposta ricevuta'}, {value:'nessuna_risposta',label:'Nessuna risposta'}
];
export const CALL_STATUSES: Array<{value:CallStatus;label:string}> = [
  {value:'non_prevista',label:'Non prevista'}, {value:'da_fissare',label:'Da fissare'}, {value:'fissata',label:'Fissata'},
  {value:'fatta',label:'Fatta'}, {value:'no_show',label:'No show'}
];
export const POC_STATUSES: Array<{value:PocStatus;label:string}> = [
  {value:'non_previsto',label:'Non previsto'}, {value:'da_proporre',label:'Da proporre'}, {value:'proposto',label:'Proposto'},
  {value:'in_corso',label:'In corso'}, {value:'completato',label:'Completato'}
];
export const labelFor = <T extends string>(items:Array<{value:T;label:string}>, value:string) => items.find(item=>item.value===value)?.label || value;
