import { ClientDependencies } from '../../../common/ClientDependencies';
import { BackendApiClient } from '../../../common/network/BackendApiClient';
import {
  AgentRun,
  ChatMessage,
  ChatThread,
  CreateRunBody,
  CreateThreadBody,
  InteractionResponseBody,
  LegacyResumeRunBody,
  ResumeDecisionBody,
  RunEventHandler,
  RunMessageBody
} from '../domain/ChatModels';
import { AgentStreamClient } from './AgentStreamClient';

export class ChatRepository {
  private readonly api: BackendApiClient;
  private readonly stream: AgentStreamClient;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.api = dependencies.api;
    this.stream = new AgentStreamClient(this.api);
  }

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
    const interactionId = run.pending_interaction?.['interaction_id'];
    if (typeof interactionId === 'string') {
      const body: InteractionResponseBody = {
        response: { action: approved ? 'confirm' : 'cancel' },
        expected_version: run.version
      };
      return this.api.post<AgentRun>(
        `/runs/${run.id}/interactions/${interactionId}/respond`,
        body,
        this.key('interaction')
      );
    }
    const response: ResumeDecisionBody = { action: approved ? 'confirm' : 'cancel' };
    const body: LegacyResumeRunBody = {
      interrupt_id: run.interrupt_id,
      response: response,
      expected_version: run.version
    };
    return this.api.post<AgentRun>(`/runs/${run.id}/resume`, body, this.key('resume'));
  }

  followRun(runId: string, onEvent: RunEventHandler, afterSequence?: number): Promise<void> {
    return this.stream.follow(`/runs/${runId}/events`, onEvent, afterSequence);
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
