export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface ChatThread {
  id: string;
}

export interface AgentRun {
  id: string;
  status: string;
  status_label?: string;
  interrupt_id?: string;
  interrupt?: Record<string, Object>;
  error_code?: string;
  version: number;
  stream_url: string;
}

export interface RunEventEnvelope {
  event_id: string;
  event: string;
  run_id: string;
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
  approved: boolean;
}

export interface ResumeRunBody {
  interrupt_id?: string;
  response: ResumeDecisionBody;
  expected_version: number;
}
