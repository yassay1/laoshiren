import { AuthProvider, AuthSession } from './AuthProvider';
import { BackendApiClient } from '../network/BackendApiClient';

interface LoginResponse {
  access_token: string;
  user_id: string;
  expires_at: string;
}

interface EmptyRequestBody {
}

export class SessionManager {
  private readonly api: BackendApiClient;
  private readonly auth: AuthProvider;

  constructor(api: BackendApiClient, auth: AuthProvider) {
    this.api = api;
    this.auth = auth;
  }

  async refresh(): Promise<boolean> {
    try {
      const body: EmptyRequestBody = {};
      const response = await this.api.post<LoginResponse>('/auth/refresh', body, 'auth-refresh');
      const session: AuthSession = {
        accessToken: response.access_token,
        userId: response.user_id,
        expiresAt: response.expires_at
      };
      await this.auth.saveSession(session);
      return true;
    } catch (_) {
      await this.auth.clearSession();
      return false;
    }
  }

  async getSession(): Promise<AuthSession | undefined> {
    return this.auth.getSession();
  }

  async signIn(): Promise<AuthSession> {
    return this.auth.signIn();
  }

  async signOut(): Promise<void> {
    try {
      const token = await this.auth.getAccessToken();
      if (token.length > 0) {
        const body: EmptyRequestBody = {};
        await this.api.post<void>('/auth/logout', body, 'auth-logout');
      }
    } catch (_) {
      // Local sign-out must still complete when the backend is unreachable.
    } finally {
      await this.auth.signOut();
    }
  }
}
