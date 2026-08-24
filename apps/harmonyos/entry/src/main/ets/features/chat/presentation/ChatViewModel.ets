import { ChatRepository } from '../data/ChatRepository';
import { AgentRun, ChatMessage, RunEventEnvelope } from '../domain/ChatModels';

@Observed
export class ChatViewModel {
  messages: ChatMessage[] = [];
  draft: string = '';
  busy: boolean = false;
  statusText: string = '';
  errorText: string = '';
  waitingRun?: AgentRun;
  private threadId: string = '';
  private lastDraft: string = '';
  private lastRunKey: string = '';
  private readonly repository: ChatRepository = new ChatRepository();

  async initialize(): Promise<void> {
    if (this.threadId.length > 0) return;
    this.busy = true;
    this.statusText = '正在连接…';
    try {
      const thread = await this.repository.createThread();
      this.threadId = thread.id;
      await this.refreshMessages();
      this.errorText = '';
    } catch (error) {
      this.errorText = this.messageOf(error, '暂时无法连接服务，请确认后端已启动');
    } finally {
      this.busy = false;
      this.statusText = '';
    }
  }

  async send(): Promise<void> {
    const content = this.draft.trim();
    if (content.length === 0 || this.busy) return;
    if (this.threadId.length === 0) {
      await this.initialize();
      if (this.threadId.length === 0) return;
    }
    this.lastDraft = content;
    this.lastRunKey = this.repository.newIdempotencyKey('run');
    this.draft = '';
    this.busy = true;
    this.errorText = '';
    this.waitingRun = undefined;
    this.statusText = '正在理解和处理…';
    try {
      const run = await this.repository.createRun(this.threadId, content, this.lastRunKey);
      await this.refreshMessages();
      await this.follow(run);
    } catch (error) {
      this.errorText = this.messageOf(error, '这次没有处理成功，可以重试');
    } finally {
      this.busy = false;
      if (this.waitingRun === undefined) this.statusText = '';
    }
  }

  async retry(): Promise<void> {
    if (this.lastDraft.length === 0) {
      await this.initialize();
      return;
    }
    this.busy = true;
    this.errorText = '';
    try {
      const run = await this.repository.createRun(
        this.threadId,
        this.lastDraft,
        this.lastRunKey
      );
      await this.follow(run);
    } catch (error) {
      this.errorText = this.messageOf(error, 'Retry failed');
    } finally {
      this.busy = false;
    }
  }

  async respondToInterrupt(approved: boolean): Promise<void> {
    const run = this.waitingRun;
    if (run === undefined || this.busy) return;
    this.busy = true;
    this.errorText = '';
    this.statusText = approved ? '已确认，正在继续…' : '已拒绝，正在收尾…';
    try {
      const resumed = await this.repository.resumeRun(run, approved);
      this.waitingRun = undefined;
      await this.follow(resumed);
    } catch (error) {
      this.errorText = this.messageOf(error, '提交确认失败，请重试');
    } finally {
      this.busy = false;
      if (this.waitingRun === undefined) this.statusText = '';
    }
  }

  close(): void {
    this.repository.closeStream();
  }

  private async follow(run: AgentRun): Promise<void> {
    let interrupted = false;
    await this.repository.followRun(run.id, (event: RunEventEnvelope) => {
      if (event.event === 'assistant.message') {
        this.statusText = '正在整理回复…';
      } else if (event.event === 'status.updated' || event.event === 'tool.started') {
        this.statusText = '正在处理…';
      } else if (event.event === 'interrupt.required') {
        interrupted = true;
        this.repository.closeStream();
      } else if (event.event === 'run.failed') {
        this.errorText = '处理失败，可以重试上一条消息';
      }
    }).catch((error: Error) => {
      if (!interrupted) throw error;
    });
    const latest = await this.repository.getRun(run.id);
    if (latest.status === 'WAITING_USER') {
      this.waitingRun = latest;
      this.statusText = '需要你的确认';
    } else if (latest.status === 'FAILED') {
      this.errorText = `处理失败${latest.error_code === undefined ? '' : `：${latest.error_code}`}`;
    }
    await this.refreshMessages();
  }

  private async refreshMessages(): Promise<void> {
    this.messages = await this.repository.listMessages(this.threadId);
  }

  private messageOf(error: Object, fallback: string): string {
    if (error instanceof Error && error.message.length > 0) return error.message;
    return fallback;
  }
}
