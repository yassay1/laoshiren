import { http } from '@kit.NetworkKit';
import { AuthProvider } from '../auth/AuthProvider';

export class ApiError extends Error {
  readonly statusCode: number;

  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
  }
}

export class BackendApiClient {
  private readonly baseUrl: string;
  private readonly auth: AuthProvider;

  constructor(baseUrl: string, auth: AuthProvider) {
    this.baseUrl = baseUrl;
    this.auth = auth;
  }

  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, http.RequestMethod.GET);
  }

  async post<T>(path: string, body: Object, idempotencyKey: string): Promise<T> {
    return this.request<T>(path, http.RequestMethod.POST, body, idempotencyKey);
  }

  async put<T>(path: string, body: Object, idempotencyKey: string): Promise<T> {
    return this.request<T>(path, http.RequestMethod.PUT, body, idempotencyKey);
  }

  streamUrl(path: string): string {
    if (this.baseUrl.length === 0) {
      throw new Error('后端 HTTPS 服务地址尚未配置');
    }
    return `${this.baseUrl}${path}`;
  }

  async authorizationHeader(): Promise<string> {
    return `Bearer ${await this.auth.getAccessToken()}`;
  }

  private async request<T>(path: string, method: http.RequestMethod, body?: Object,
    idempotencyKey?: string): Promise<T> {
    const request = http.createHttp();
    const headers: Record<string, string> = {
      'Authorization': await this.authorizationHeader(),
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
      return raw.length === 0 ? (undefined as T) : JSON.parse(raw) as T;
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
