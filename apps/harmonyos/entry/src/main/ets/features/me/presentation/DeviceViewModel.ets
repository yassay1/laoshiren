import { ClientDependencies } from '../../../common/ClientDependencies';
import { DeviceIdentityStore } from '../../../common/device/DeviceIdentityStore';
import { AuthProvider } from '../../../common/auth/AuthProvider';
import { PushProvider } from '../../../common/push/PushProvider';
import { DeviceRepository } from '../data/DeviceRepository';
import { Device } from '../domain/DeviceModels';

@Observed
export class DeviceViewModel {
  device?: Device;
  busy: boolean = false;
  errorText: string = '';
  pushStatus: string = '等待登录';
  private readonly deviceIdentity: DeviceIdentityStore;
  private readonly repository: DeviceRepository;
  private readonly auth: AuthProvider;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.repository = new DeviceRepository(dependencies.api);
    this.auth = dependencies.auth;
    this.push = dependencies.push;
    this.deviceIdentity = dependencies.deviceIdentity;
    this.pushStatus = dependencies.pushMode === 'mock' ? '开发环境模拟推送' : '等待登录';
  }

  private readonly push: PushProvider;

  async initialize(): Promise<void> {
    if (this.busy || this.pushStatus === '推送令牌已上传') return;
    if (await this.auth.getSession() === undefined) return;
    this.busy = true;
    this.errorText = '';
    try {
      if (this.device === undefined) {
        const deviceId = await this.deviceIdentity.getId();
        this.device = await this.repository.register(deviceId, 'Asia/Shanghai');
      }
      const token = await this.push.getToken();
      if (token !== undefined && token.length > 0) {
        await this.repository.uploadPushToken(this.device.device_id, token);
        this.pushStatus = '推送令牌已上传';
      } else if (this.pushStatus !== '开发环境模拟推送') {
        this.pushStatus = '未取得推送令牌';
      }
    } catch (error) {
      this.errorText = error instanceof Error ? error.message : '暂时无法注册设备';
      this.pushStatus = '设备或推送初始化失败';
    } finally {
      this.busy = false;
    }
  }

  reset(): void {
    this.device = undefined;
    this.errorText = '';
    this.pushStatus = '等待登录';
  }
}
