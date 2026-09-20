import { BusinessError } from '@kit.BasicServicesKit';
import { pushService } from '@kit.PushKit';
import { PushProvider } from './PushProvider';

export enum HuaweiPushErrorKind {
  NETWORK = 'NETWORK',
  APP_IDENTITY = 'APP_IDENTITY',
  NOT_ACTIVATED = 'NOT_ACTIVATED',
  UNSUPPORTED = 'UNSUPPORTED',
  SERVICE = 'SERVICE'
}

export class HuaweiPushError extends Error {
  readonly kind: HuaweiPushErrorKind;
  readonly errorCode: number;

  constructor(kind: HuaweiPushErrorKind, message: string, errorCode: number = 0) {
    super(message);
    this.kind = kind;
    this.errorCode = errorCode;
  }
}

const PUSH_CONNECT_FAILED = 1000900008;
const PUSH_ILLEGAL_APP_IDENTITY = 1000900010;
const PUSH_NETWORK_UNAVAILABLE = 1000900011;
const PUSH_RIGHTS_NOT_ACTIVATED = 1000900012;
const PUSH_CROSS_LOCATION = 1000900013;
const PUSH_DEVICE_UNSUPPORTED = 1000900014;

/** Push Kit adapter. Token upload remains in DeviceViewModel and DeviceRepository. */
export class HuaweiPushProvider implements PushProvider {
  async getToken(): Promise<string | undefined> {
    try {
      const token = (await pushService.getToken()).trim();
      if (token.length === 0) {
        throw new HuaweiPushError(
          HuaweiPushErrorKind.SERVICE,
          'Push Kit 未返回有效 Token'
        );
      }
      return token;
    } catch (error) {
      if (error instanceof HuaweiPushError) {
        throw error;
      }
      throw this.mapError(error as BusinessError);
    }
  }

  async deleteToken(): Promise<void> {
    try {
      await pushService.deleteToken();
    } catch (error) {
      throw this.mapError(error as BusinessError);
    }
  }

  private mapError(error: BusinessError): HuaweiPushError {
    if (error.code === PUSH_CONNECT_FAILED || error.code === PUSH_NETWORK_UNAVAILABLE) {
      return new HuaweiPushError(
        HuaweiPushErrorKind.NETWORK,
        'Push Kit 网络连接失败，请稍后重试',
        error.code
      );
    }
    if (error.code === PUSH_ILLEGAL_APP_IDENTITY) {
      return new HuaweiPushError(
        HuaweiPushErrorKind.APP_IDENTITY,
        'Push Kit 应用身份校验失败',
        error.code
      );
    }
    if (error.code === PUSH_RIGHTS_NOT_ACTIVATED) {
      return new HuaweiPushError(
        HuaweiPushErrorKind.NOT_ACTIVATED,
        'Push Kit 服务尚未开通',
        error.code
      );
    }
    if (error.code === PUSH_CROSS_LOCATION || error.code === PUSH_DEVICE_UNSUPPORTED) {
      return new HuaweiPushError(
        HuaweiPushErrorKind.UNSUPPORTED,
        '当前设备或区域不支持 Push Kit',
        error.code
      );
    }
    return new HuaweiPushError(
      HuaweiPushErrorKind.SERVICE,
      'Push Kit 服务暂时不可用',
      error.code
    );
  }
}
