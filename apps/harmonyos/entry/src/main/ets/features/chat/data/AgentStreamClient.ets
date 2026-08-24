import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { ApiClient } from '../../../common/network/ApiClient';
import { RunEventEnvelope, RunEventHandler } from '../domain/ChatModels';

export class AgentStreamClient {
  private activeRequest?: http.HttpRequest;
  private buffer: string = '';

  private readonly api: ApiClient;

  constructor(api: ApiClient) {
    this.api = api;
  }

  async follow(path: string, onEvent: RunEventHandler): Promise<void> {
    this.close();
    const request = http.createHttp();
    this.activeRequest = request;
    this.buffer = '';
    const decoder = util.TextDecoder.create('utf-8');

    request.on('dataReceive', (chunk: ArrayBuffer) => {
      this.buffer += decoder.decodeWithStream(new Uint8Array(chunk), { stream: true });
      this.consume(onEvent);
    });
    request.on('dataEnd', () => {
      this.consume(onEvent, true);
    });

    try {
      const statusCode = await request.requestInStream(this.api.streamUrl(path), {
        method: http.RequestMethod.GET,
        header: {
          'Authorization': this.api.authorizationHeader(),
          'Accept': 'text/event-stream'
        },
        connectTimeout: 10000,
        readTimeout: 120000,
        usingCache: false
      });
      if (statusCode < 200 || statusCode >= 300) {
        throw new Error(`事件流连接失败（${statusCode}）`);
      }
    } finally {
      if (this.activeRequest === request) {
        this.activeRequest = undefined;
      }
      request.destroy();
    }
  }

  close(): void {
    if (this.activeRequest !== undefined) {
      this.activeRequest.destroy();
      this.activeRequest = undefined;
    }
  }

  private consume(onEvent: RunEventHandler, flush: boolean = false): void {
    const blocks = this.buffer.split('\n\n');
    this.buffer = flush ? '' : blocks.pop() ?? '';
    blocks.forEach((block: string) => {
      const line = block.split('\n').find((value: string) => value.startsWith('data:'));
      if (line === undefined) {
        return;
      }
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as RunEventEnvelope);
      } catch (_) {
      }
    });
  }
}
