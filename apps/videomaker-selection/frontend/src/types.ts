export type Decision = 'da_valutare' | 'scartato' | 'riserva' | 'selezionato';
export type EmailStatus = 'da_contattare' | 'email_inviata' | 'risposta_ricevuta' | 'nessuna_risposta';
export type CallStatus = 'non_prevista' | 'da_fissare' | 'fissata' | 'fatta' | 'no_show';
export type PocStatus = 'non_previsto' | 'da_proporre' | 'proposto' | 'in_corso' | 'completato';

export interface Activity {
  id: string; candidate_id: string; kind: string; summary: string;
  details: Record<string, unknown>; occurred_at: string; created_at: string;
}
export interface Candidate {
  id: string; source_response_number: number | null; source_submitted_at: string; name: string; email: string;
  city: string; bio: string; work_status: string; has_vat: boolean; profile_code: string; profile_label: string; profile_answer:string;
  traits: string[]; social_usage: string; autonomy: string; workflow:string; platforms: string[]; opportunity: string; capacity: string;
  price_proposal: string; portfolio_url: string; test_url: string; additional_info: string; duplicate_submissions: unknown[];
  privacy_accepted:boolean; reviewed: boolean; review_rank:number|null; annotation: string; specialty: string; score_portfolio: number | null; score_budget: number | null;
  score_test: number | null; review_score: number | null; form_fit_score: number | null; summary: string;
  decision: Decision; email_status: EmailStatus; call_status: CallStatus; poc_status: PocStatus;
  next_action: string; next_action_due: string; process_notes: string; favorite: boolean; archived: boolean;
  created_at: string; updated_at: string; activities?: Activity[];
}
export interface Stats {
  total: number; reviewed: number; favorites: number; due_actions: number;
  decision: Record<string, number>; email: Record<string, number>; call: Record<string, number>; poc: Record<string, number>;
}
export interface Filters {
  query: string; decision: string; email_status: string; call_status: string; poc_status: string;
  reviewed: string; work: string; archived:string; sort: string; favorite: boolean;
}
export interface ViewState { mode: string; query: string; decision: string; email_status:string; title: string; refs: Array<{entity_type:string;entity_id:string}>; updated_at?: string }
