import { http } from '@kit.NetworkKit';

export class ApiError extends Error {
  readonly statusCode: number;

  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
  }
}

export class ApiClient {
  private readonly baseUrl: string = 'http://127.0.0.1:8000/api/v1';
  private readonly token: string = 'change-me';

  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, http.RequestMethod.GET);
  }

  async post<T>(path: string, body: Object, idempotencyKey: string): Promise<T> {
    return this.request<T>(path, http.RequestMethod.POST, body, idempotencyKey);
  }

  streamUrl(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  authorizationHeader(): string {
    return `Bearer ${this.token}`;
  }

  private async request<T>(path: string, method: http.RequestMethod, body?: Object,
    idempotencyKey?: string): Promise<T> {
    const request = http.createHttp();
    const headers: Record<string, string> = {
      'Authorization': this.authorizationHeader(),
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (idempotencyKey !== undefined) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    try {
      const response = await request.request(this.streamUrl(path), {
        method: method,
        header: headers,
        extraData: body === undefined ? '' : JSON.stringify(body),
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: 10000,
        readTimeout: 60000,
        usingCache: false
      });
      const statusCode = response.responseCode;
      const raw = response.result as string;
      if (statusCode < 200 || statusCode >= 300) {
        throw new ApiError(statusCode, this.readError(raw));
      }
      return JSON.parse(raw) as T;
    } finally {
      request.destroy();
    }
  }

  private readError(raw: string): string {
    try {
      const parsed = JSON.parse(raw) as Record<string, Object>;
      const detail = parsed['detail'];
      if (typeof detail === 'string') {
        return detail;
      }
    } catch (_) {
    }
    return '请求失败，请稍后重试';
  }
}
