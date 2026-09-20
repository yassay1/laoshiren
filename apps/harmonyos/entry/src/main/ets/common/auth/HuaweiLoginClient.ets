import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { AuthSession } from './AuthProvider';
import { ApiError } from '../network/BackendApiClient';

interface HuaweiLoginRequest {
  authorization_code: string;
}

interface HuaweiLoginResponse {
  access_token: string;
  user_id: string;
  expires_at: string;
}

/** Anonymous backend client used only to exchange a Huawei authorization code. */
export class HuaweiLoginClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async exchangeAuthorizationCode(authorizationCode: string): Promise<AuthSession> {
    if (this.baseUrl.length === 0) {
      throw new Error('后端 HTTPS 服务地址尚未配置');
    }
    const cleanCode = authorizationCode.trim();
    if (cleanCode.length === 0) {
      throw new Error('Huawei authorization code is empty');
    }
    const requestBody: HuaweiLoginRequest = {
      authorization_code: cleanCode
    };
    const request = http.createHttp();
    try {
      const response = await request.request(`${this.baseUrl}/auth/huawei/login`, {
        method: http.RequestMethod.POST,
        header: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Idempotency-Key': `huawei-login-${util.generateRandomUUID()}`
        },
        extraData: JSON.stringify(requestBody),
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: 10000,
        readTimeout: 30000,
        usingCache: false
      });
      const statusCode = response.responseCode;
      const raw = response.result as string;
      if (statusCode < 200 || statusCode >= 300) {
        throw new ApiError(statusCode, this.readError(raw));
      }
      const body = JSON.parse(raw) as HuaweiLoginResponse;
      if (typeof body.access_token !== 'string' || body.access_token.length === 0 ||
        typeof body.user_id !== 'string' || body.user_id.length === 0 ||
        typeof body.expires_at !== 'string' || body.expires_at.length === 0) {
        throw new Error('Backend returned an invalid login session');
      }
      return {
        accessToken: body.access_token,
        userId: body.user_id,
        expiresAt: body.expires_at
      };
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('登录请求失败，请稍后重试');
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
    return '登录请求失败，请稍后重试';
  }
}
