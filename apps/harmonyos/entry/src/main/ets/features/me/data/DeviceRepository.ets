import { BackendApiClient } from '../../../common/network/BackendApiClient';
import { Device, PushTokenBody, RegisterDeviceBody } from '../domain/DeviceModels';

export class DeviceRepository {
  private readonly api: BackendApiClient;

  constructor(api: BackendApiClient) {
    this.api = api;
  }

  register(deviceId: string, timezone: string): Promise<Device> {
    const body: RegisterDeviceBody = {
      device_id: deviceId,
      timezone: timezone,
      platform: 'HARMONYOS'
    };
    return this.api.post<Device>('/devices/register', body, `device-${deviceId}`);
  }

  uploadPushToken(deviceId: string, token: string): Promise<void> {
    const body: PushTokenBody = { push_token: token, provider: 'HUAWEI' };
    return this.api.put<void>(`/devices/${deviceId}/push-token`, body, `push-token-${deviceId}`);
  }
}
