export interface PushProvider {
  getToken(): Promise<string | undefined>;
  deleteToken(): Promise<void>;
}

/** Development-only adapter. Real Push Kit calls stay outside UI and ViewModel code. */
export class MockPushProvider implements PushProvider {
  private token?: string;

  async getToken(): Promise<string | undefined> {
    return this.token;
  }

  async deleteToken(): Promise<void> {
    this.token = undefined;
  }
}
