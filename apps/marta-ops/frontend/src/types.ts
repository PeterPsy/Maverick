export type ViewId =
  | "today"
  | "work"
  | "deliveries"
  | "contacts"
  | "tasks"
  | "admin"
  | "ideas";
export type WorkPanelTab = "details" | "deliverables" | "tasks" | "history";
export type CollaborationKind =
  | "partnership"
  | "organic"
  | "event"
  | "giuntitrail";
export type CollaborationPhase =
  | "lead"
  | "proposal"
  | "confirmed"
  | "production"
  | "approval"
  | "scheduled"
  | "published"
  | "completed"
  | "paused"
  | "lost";
export type PaymentStatus =
  | "not_due"
  | "to_invoice"
  | "invoiced"
  | "overdue"
  | "paid";
export type ContractStatus = "not_needed" | "draft" | "sent" | "signed";
export type DeliverableStatus =
  | "planned"
  | "in_progress"
  | "approval"
  | "scheduled"
  | "published";
export type IdeaStatus = "inbox" | "selected" | "scheduled" | "archived";

export type Deliverable = {
  id: string;
  title: string;
  status: DeliverableStatus;
  due_date: string;
  created_at: string;
  updated_at: string;
};

export type LinkedDocument = {
  id: string;
  name: string;
  workspace_relative_path: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  provider_app_id: string;
  linked_at: string;
};

export type MailDraftReference = {
  id?: string;
  connection_id?: string;
  provider_app_id?: string;
  updated_at?: string;
};

export type CalendarEventReference = {
  id?: string;
  revision?: number;
  connection_id?: string;
  calendar_id?: string;
  provider_app_id?: string;
  start_date?: string;
  updated_at?: string;
};

export type Collaboration = {
  id: string;
  title: string;
  partner: string;
  partner_email: string;
  contact_id: string;
  pipeline_order: number;
  kind: CollaborationKind;
  phase: CollaborationPhase;
  next_action: string;
  due_date: string;
  value_minor: number;
  payment_status: PaymentStatus;
  contract_status: ContractStatus;
  rights_expiry_date: string;
  notes: string;
  deliverables: Deliverable[];
  documents: LinkedDocument[];
  mail_draft: MailDraftReference;
  calendar_event: CalendarEventReference;
  created_at: string;
  updated_at: string;
};

export type Idea = {
  id: string;
  title: string;
  pillar: string;
  note: string;
  status: IdeaStatus;
  created_at: string;
  updated_at: string;
};

export type MartaOpsState = {
  schema_version: string;
  collaborations: Collaboration[];
  ideas: Idea[];
  contacts: Contact[];
  tasks: Task[];
  activity: Activity[];
  integration_options: IntegrationOptions;
  integration_preferences: IntegrationPreferences;
};

export type MailConnectionOption = {
  id: string;
  label: string;
  email: string;
  provider: string;
};

export type CalendarConnectionOption = {
  id: string;
  label: string;
};

export type CalendarOption = {
  connection_id: string;
  provider_calendar_id: string;
  summary: string;
  timezone: string;
  primary: boolean;
  selected: boolean;
};

export type IntegrationOptions = {
  mail_provider_app_id: string;
  calendar_provider_app_id: string;
  storage_provider_app_id: string;
  mail_connections: MailConnectionOption[];
  calendar_connections: CalendarConnectionOption[];
  calendar_calendars: CalendarOption[];
  refreshed_at: string;
};

export type IntegrationPreferences = {
  mail_connection_id: string;
  calendar_connection_id: string;
  calendar_id: string;
};

export type Contact = {
  id: string;
  name: string;
  company: string;
  role: string;
  email: string;
  phone: string;
  tags: string[];
  notes: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
};

export type Task = {
  id: string;
  title: string;
  kind: "task" | "call" | "email" | "meeting";
  due_date: string;
  contact_id: string;
  collaboration_id: string;
  done: boolean;
  completed_at: string;
  notes: string;
  created_at: string;
  updated_at: string;
};

export type Activity = {
  id: string;
  kind: "note" | "change";
  title: string;
  text: string;
  contact_id: string;
  collaboration_id: string;
  created_at: string;
};

export type ContactDraft = Omit<Contact, "id" | "created_at" | "updated_at">;
export type TaskDraft = Omit<
  Task,
  "id" | "created_at" | "updated_at" | "completed_at"
>;

export type BackendPayload = {
  app_id?: string;
  status?: string;
  state: MartaOpsState;
  collaboration?: Collaboration;
  deliverable?: Deliverable;
  idea?: Idea;
  contact?: Contact;
  task?: Task;
  activity?: Activity;
  dependency_backend_request_results?: Array<{
    dependency_alias: string;
    provider_app_id?: string;
    status: string;
    status_code: number;
    callback_status_code?: number;
    error?: string;
  }>;
};

export type WorkDraft = Omit<
  Collaboration,
  | "id"
  | "deliverables"
  | "documents"
  | "mail_draft"
  | "calendar_event"
  | "created_at"
  | "updated_at"
  | "value_minor"
  | "pipeline_order"
> & {
  value_euros: string;
};
