import BuildProfile from 'BuildProfile';

export type RuntimeMode = 'debug' | 'release';

export class RuntimeConfig {
  readonly mode: RuntimeMode;
  readonly backendApiUrl: string;
  readonly backendConfigured: boolean;
  readonly debugAuthToken: string;

  private constructor(mode: RuntimeMode, backendApiUrl: string, debugAuthToken: string) {
    this.mode = mode;
    this.backendApiUrl = backendApiUrl;
    this.backendConfigured = backendApiUrl.length > 0;
    this.debugAuthToken = debugAuthToken;
  }

  static current(): RuntimeConfig {
    const mode: string = String(BuildProfile.runtimeMode);
    const url = BuildProfile.backendApiUrl.trim().replace(/\/$/, '');
    if (mode !== 'debug' && mode !== 'release') {
      throw new Error('未知运行模式，已停止初始化');
    }
    if (mode !== String(BuildProfile.BUILD_MODE_NAME)) {
      throw new Error('运行模式与构建模式不一致，已停止初始化');
    }
    if (mode === 'release' && url.length > 0) {
      const validHttps = /^https:\/\/[a-z0-9][a-z0-9.-]*(?::[0-9]+)?(?:\/|$)/i.test(url);
      const host = url.replace(/^https:\/\//i, '').split('/')[0].split(':')[0].toLowerCase();
      const localHost = host === 'localhost' || host.endsWith('.localhost') || /^[0-9.]+$/.test(host);
      if (!validHttps || localHost) {
        throw new Error('Release 后端地址必须是非本机 HTTPS 服务');
      }
    }
    if (mode === 'debug' && url.length === 0) {
      throw new Error('Debug 后端地址未配置');
    }
    if (mode === 'release' && BuildProfile.debugAuthToken.length > 0) {
      throw new Error('Release 包含开发认证令牌，已停止初始化');
    }
    return new RuntimeConfig(mode as RuntimeMode, url, BuildProfile.debugAuthToken);
  }

  backendLabel(): string {
    if (!this.backendConfigured) {
      return '未配置 HTTPS 服务地址';
    }
    return this.mode === 'debug' ? '本地开发服务' : 'HTTPS 服务已配置';
  }
}
