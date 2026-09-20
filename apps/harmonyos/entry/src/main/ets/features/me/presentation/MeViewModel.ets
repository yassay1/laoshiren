import { ClientDependencies } from '../../../common/ClientDependencies';
import { AuthSession } from '../../../common/auth/AuthProvider';
import { HuaweiAuthError, HuaweiAuthErrorKind } from '../../../common/auth/HuaweiAuthProvider';
import { SessionManager } from '../../../common/auth/SessionManager';
import { ApiError } from '../../../common/network/BackendApiClient';
import { MeRepository } from '../data/MeRepository';
import { UserProfile } from '../domain/MeModels';

export type AuthStatus = 'SIGNED_OUT' | 'AUTHENTICATED' | 'SESSION_EXPIRED';

@Observed
export class MeViewModel {
  profile?: UserProfile;
  authStatus: AuthStatus = 'SIGNED_OUT';
  busy: boolean = false;
  errorText: string = '';
  readonly usesHuaweiAccount: boolean;
  readonly backendConfigured: boolean;
  readonly backendLabel: string;
  readonly reminderLabel: string;
  private readonly repository: MeRepository;
  private readonly sessionManager: SessionManager;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.usesHuaweiAccount = dependencies.authMode === 'huawei';
    this.backendConfigured = dependencies.runtime.backendConfigured;
    this.backendLabel = dependencies.runtime.backendLabel();
    this.reminderLabel = dependencies.reminderAvailable ? '可用' : '暂未开放';
    this.repository = new MeRepository(dependencies.api);
    this.sessionManager = new SessionManager(dependencies.api, dependencies.auth);
  }

  async initialize(): Promise<void> {
    if (this.busy) return;
    const session = await this.sessionManager.getSession();
    if (session === undefined) {
      this.authStatus = 'SIGNED_OUT';
      this.profile = undefined;
      return;
    }
    this.authStatus = 'AUTHENTICATED';
    this.busy = true;
    this.errorText = '';
    try {
      this.profile = await this.loadProfile();
    } catch (error) {
      if (error instanceof ApiError && error.statusCode === 401) {
        this.authStatus = 'SESSION_EXPIRED';
      }
      this.errorText = error instanceof Error ? error.message : 'Unable to load account';
    } finally {
      this.busy = false;
    }
  }

  async signIn(): Promise<void> {
    if (this.busy) return;
    if (!this.backendConfigured) {
      this.errorText = '后端 HTTPS 服务地址尚未配置';
      return;
    }
    this.busy = true;
    this.errorText = '';
    try {
      const session: AuthSession = await this.sessionManager.signIn();
      this.authStatus = session.accessToken.length > 0 ? 'AUTHENTICATED' : 'SESSION_EXPIRED';
      this.profile = undefined;
    } catch (error) {
      this.authStatus = 'SIGNED_OUT';
      if (error instanceof HuaweiAuthError && error.kind === HuaweiAuthErrorKind.CANCELED) {
        this.errorText = '';
      } else {
        this.errorText = error instanceof Error ? error.message : '登录失败，请稍后重试';
      }
    } finally {
      this.busy = false;
    }
  }

  async signOut(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      await this.sessionManager.signOut();
      this.authStatus = 'SIGNED_OUT';
      this.profile = undefined;
      this.errorText = '';
    } finally {
      this.busy = false;
    }
  }

  private async loadProfile(): Promise<UserProfile> {
    try {
      return await this.repository.getProfile();
    } catch (error) {
      if (error instanceof ApiError && error.statusCode === 401) {
        if (await this.sessionManager.refresh()) {
          return this.repository.getProfile();
        }
      }
      if (error instanceof Error) throw error;
      throw new Error('Session expired');
    }
  }
}
