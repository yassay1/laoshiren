import { common } from '@kit.AbilityKit';
import { authentication } from '@kit.AccountKit';
import { util } from '@kit.ArkTS';
import { BusinessError } from '@kit.BasicServicesKit';
import { AuthProvider, AuthSession } from './AuthProvider';
import { HuaweiLoginClient } from './HuaweiLoginClient';

export enum HuaweiAuthErrorKind {
  CANCELED = 'CANCELED',
  ACCOUNT_KIT = 'ACCOUNT_KIT',
  BACKEND = 'BACKEND',
  INVALID_RESPONSE = 'INVALID_RESPONSE'
}

export class HuaweiAuthError extends Error {
  readonly kind: HuaweiAuthErrorKind;
  readonly errorCode: number;

  constructor(kind: HuaweiAuthErrorKind, message: string, errorCode: number = 0) {
    super(message);
    this.kind = kind;
    this.errorCode = errorCode;
  }
}

const HUAWEI_USER_CANCELED = 1001502012;
const HUAWEI_NETWORK_ERROR = 1001502005;
const HUAWEI_LOGIN_OUT = 1001502001;
const HUAWEI_REQUEST_REFUSED = 1001500002;

/** Production Account Kit adapter. Business sessions remain owned by the backend. */
export class HuaweiAuthProvider implements AuthProvider {
  private readonly context: common.Context;
  private readonly loginClient: HuaweiLoginClient;
  private session?: AuthSession;

  constructor(context: common.Context, loginClient: HuaweiLoginClient) {
    this.context = context;
    this.loginClient = loginClient;
  }

  async getAccessToken(): Promise<string> {
    return this.session?.accessToken ?? '';
  }

  async getSession(): Promise<AuthSession | undefined> {
    return this.session;
  }

  async signIn(): Promise<AuthSession> {
    const request = new authentication.HuaweiIDProvider().createLoginWithHuaweiIDRequest();
    request.forceLogin = true;
    request.state = util.generateRandomUUID();
    request.idTokenSignAlgorithm = authentication.IdTokenSignAlgorithm.PS256;

    let response: authentication.LoginWithHuaweiIDResponse;
    try {
      const controller = new authentication.AuthenticationController(this.context);
      response = await controller.executeRequest(request) as authentication.LoginWithHuaweiIDResponse;
    } catch (error) {
      throw this.mapAccountKitError(error as BusinessError);
    }

    const requestState = request.state || '';
    const responseState = response.state || '';
    if (requestState !== responseState) {
      throw new HuaweiAuthError(
        HuaweiAuthErrorKind.INVALID_RESPONSE,
        '华为账号登录校验失败，请重试'
      );
    }
    const authorizationCode = response.data?.authorizationCode?.trim() ?? '';
    if (authorizationCode.length === 0) {
      throw new HuaweiAuthError(
        HuaweiAuthErrorKind.INVALID_RESPONSE,
        '华为账号未返回有效授权码'
      );
    }

    try {
      const session = await this.loginClient.exchangeAuthorizationCode(authorizationCode);
      await this.saveSession(session);
      return session;
    } catch (error) {
      const message = error instanceof Error ? error.message : '登录服务暂时不可用';
      throw new HuaweiAuthError(HuaweiAuthErrorKind.BACKEND, message);
    }
  }

  async signOut(): Promise<void> {
    await this.clearSession();
  }

  async saveSession(session: AuthSession): Promise<void> {
    this.session = session;
  }

  async clearSession(): Promise<void> {
    this.session = undefined;
  }

  private mapAccountKitError(error: BusinessError): HuaweiAuthError {
    if (error.code === HUAWEI_USER_CANCELED) {
      return new HuaweiAuthError(HuaweiAuthErrorKind.CANCELED, '用户取消华为账号登录', error.code);
    }
    if (error.code === HUAWEI_NETWORK_ERROR) {
      return new HuaweiAuthError(
        HuaweiAuthErrorKind.ACCOUNT_KIT,
        '网络不可用，请检查网络后重试',
        error.code
      );
    }
    if (error.code === HUAWEI_LOGIN_OUT) {
      return new HuaweiAuthError(
        HuaweiAuthErrorKind.ACCOUNT_KIT,
        '请先登录华为账号后重试',
        error.code
      );
    }
    if (error.code === HUAWEI_REQUEST_REFUSED) {
      return new HuaweiAuthError(
        HuaweiAuthErrorKind.ACCOUNT_KIT,
        '登录请求正在处理中',
        error.code
      );
    }
    return new HuaweiAuthError(
      HuaweiAuthErrorKind.ACCOUNT_KIT,
      '华为账号登录失败，请稍后重试',
      error.code
    );
  }
}
