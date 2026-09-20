export interface AuthSession {
  accessToken: string;
  userId: string;
  expiresAt: string;
}

export interface AuthProvider {
  getAccessToken(): Promise<string>;
  getSession(): Promise<AuthSession | undefined>;
  signIn(): Promise<AuthSession>;
  signOut(): Promise<void>;
  saveSession(session: AuthSession): Promise<void>;
  clearSession(): Promise<void>;
}

/** Development-only adapter. A real Account Kit adapter will replace it later. */
export class MockAuthProvider implements AuthProvider {
  private readonly token: string;
  private session?: AuthSession;

  constructor(token: string) {
    this.token = token;
  }

  async getAccessToken(): Promise<string> {
    return this.session?.accessToken ?? '';
  }

  async getSession(): Promise<AuthSession | undefined> {
    return this.session;
  }

  async signIn(): Promise<AuthSession> {
    const session: AuthSession = {
      accessToken: this.token,
      userId: '00000000-0000-0000-0000-000000000001',
      expiresAt: ''
    };
    await this.saveSession(session);
    return session;
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
}
