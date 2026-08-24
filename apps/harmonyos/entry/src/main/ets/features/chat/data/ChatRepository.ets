import { ApiClient } from '../../../common/network/ApiClient';
import {
  AgentRun,
  ChatMessage,
  ChatThread,
  CreateRunBody,
  CreateThreadBody,
  ResumeDecisionBody,
  ResumeRunBody,
  RunEventHandler,
  RunMessageBody
} from '../domain/ChatModels';
import { AgentStreamClient } from './AgentStreamClient';

export class ChatRepository {
  private readonly api: ApiClient = new ApiClient();
  private readonly stream: AgentStreamClient = new AgentStreamClient(this.api);

  createThread(): Promise<ChatThread> {
    const body: CreateThreadBody = { title: '新对话' };
    return this.api.post<ChatThread>('/threads', body, this.key('thread'));
  }

  listMessages(threadId: string): Promise<ChatMessage[]> {
    return this.api.get<ChatMessage[]>(`/threads/${threadId}/messages`);
  }

  createRun(threadId: string, content: string, idempotencyKey: string): Promise<AgentRun> {
    const message: RunMessageBody = { type: 'text', content: content };
    const body: CreateRunBody = {
      thread_id: threadId,
      message: message,
      source_ids: []
    };
    return this.api.post<AgentRun>('/runs', body, idempotencyKey);
  }

  getRun(runId: string): Promise<AgentRun> {
    return this.api.get<AgentRun>(`/runs/${runId}`);
  }

  resumeRun(run: AgentRun, approved: boolean): Promise<AgentRun> {
    const response: ResumeDecisionBody = { action: approved ? 'confirm' : 'cancel' };
    const body: ResumeRunBody = {
      interrupt_id: run.interrupt_id,
      response: response,
      expected_version: run.version
    };
    return this.api.post<AgentRun>(`/runs/${run.id}/resume`, body, this.key('resume'));
  }

  followRun(runId: string, onEvent: RunEventHandler): Promise<void> {
    return this.stream.follow(`/runs/${runId}/events`, onEvent);
  }

  closeStream(): void {
    this.stream.close();
  }

  newIdempotencyKey(prefix: string): string {
    return this.key(prefix);
  }

  private key(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1000000)}`;
  }
}
