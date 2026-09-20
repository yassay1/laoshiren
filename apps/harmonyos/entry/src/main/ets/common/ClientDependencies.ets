import { common } from '@kit.AbilityKit';
import { AuthProvider, MockAuthProvider } from './auth/AuthProvider';
import { HuaweiAuthProvider } from './auth/HuaweiAuthProvider';
import { HuaweiLoginClient } from './auth/HuaweiLoginClient';
import { BackendApiClient } from './network/BackendApiClient';
import { HuaweiPushProvider } from './push/HuaweiPushProvider';
import { MockPushProvider, PushProvider } from './push/PushProvider';
import { MockReminderProvider, ReminderProvider } from './reminder/ReminderProvider';
import { UnavailableReminderProvider } from './reminder/ReminderProvider';
import { RuntimeConfig } from './RuntimeConfig';
import { DeviceIdentityStore } from './device/DeviceIdentityStore';

export type AuthProviderMode = 'mock' | 'huawei';
export type PushProviderMode = 'mock' | 'huawei';

/** Composition root for replaceable client adapters. */
export class ClientDependencies {
  private static instance?: ClientDependencies;
  readonly auth: AuthProvider;
  readonly api: BackendApiClient;
  readonly push: PushProvider;
  readonly reminder: ReminderProvider;
  readonly authMode: AuthProviderMode;
  readonly pushMode: PushProviderMode;
  readonly runtime: RuntimeConfig;
  readonly deviceIdentity: DeviceIdentityStore;
  readonly reminderAvailable: boolean;

  static initialize(context: common.Context): ClientDependencies {
    const runtime = RuntimeConfig.current();
    const release = runtime.mode === 'release';
    const authMode: AuthProviderMode = release ? 'huawei' : 'mock';
    const pushMode: PushProviderMode = release ? 'huawei' : 'mock';
    const auth: AuthProvider = release
      ? new HuaweiAuthProvider(context, new HuaweiLoginClient(runtime.backendApiUrl))
      : new MockAuthProvider(runtime.debugAuthToken);
    const push: PushProvider = release ? new HuaweiPushProvider() : new MockPushProvider();
    ClientDependencies.instance = new ClientDependencies(
      runtime,
      auth,
      authMode,
      push,
      pushMode,
      new DeviceIdentityStore(context),
      release ? new UnavailableReminderProvider() : new MockReminderProvider()
    );
    return ClientDependencies.instance;
  }

  static shared(): ClientDependencies {
    if (ClientDependencies.instance === undefined) {
      throw new Error('ClientDependencies 尚未初始化');
    }
    return ClientDependencies.instance;
  }

  private constructor(runtime: RuntimeConfig, auth: AuthProvider, authMode: AuthProviderMode,
    push: PushProvider, pushMode: PushProviderMode, deviceIdentity: DeviceIdentityStore,
    reminder: ReminderProvider) {
    this.runtime = runtime;
    this.auth = auth;
    this.api = new BackendApiClient(runtime.backendApiUrl, this.auth);
    this.push = push;
    this.reminder = reminder;
    this.authMode = authMode;
    this.pushMode = pushMode;
    this.deviceIdentity = deviceIdentity;
    this.reminderAvailable = false;
  }
}
