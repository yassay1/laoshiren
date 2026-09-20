export interface ChatMessage {
  id: string;
  thread_id?: string;
  role: string;
  content: string;
  run_id?: string;
  source_ids?: string[];
  metadata?: Record<string, Object>;
  created_at: string;
}

export interface ChatThread {
  id: string;
  title?: string;
  active_thing_id?: string;
  archived_at?: string;
  created_at?: string;
  updated_at?: string;
  replayed?: boolean;
}

export interface AgentRun {
  id: string;
  thread_id?: string;
  status: string;
  status_label?: string;
  interrupt_id?: string;
  interrupt?: Record<string, Object>;
  error_code?: string;
  version: number;
  stream_url: string;
  last_event_sequence?: number;
  pending_interaction?: Record<string, Object>;
  budget_snapshot?: Record<string, Object>;
  active_time_used_ms?: number;
  replayed?: boolean;
}

export interface RunEventEnvelope {
  event_id: string;
  sequence: number;
  event: string;
  run_id: string;
  occurred_at?: string;
  visibility?: string;
  schema_version?: number;
  data: Record<string, Object>;
}

export type RunEventHandler = (event: RunEventEnvelope) => void;

export interface CreateThreadBody {
  title: string;
}

export interface RunMessageBody {
  type: string;
  content: string;
}

export interface CreateRunBody {
  thread_id: string;
  message: RunMessageBody;
  source_ids: string[];
}

export interface ResumeDecisionBody {
  action: string;
}

export interface InteractionDecisionBody {
  action: string;
}

export interface InteractionResponseBody {
  response: InteractionDecisionBody;
  expected_version: number;
}

export interface LegacyResumeRunBody {
  interrupt_id?: string;
  response: ResumeDecisionBody;
  expected_version: number;
}
