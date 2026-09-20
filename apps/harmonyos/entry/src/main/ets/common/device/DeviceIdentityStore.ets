import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { preferences } from '@kit.ArkData';

/** One ID per installation; reuse it across pages and process restarts. */
export class DeviceIdentityStore {
  private readonly context: common.Context;
  private pendingId?: Promise<string>;

  constructor(context: common.Context) {
    this.context = context;
  }

  getId(): Promise<string> {
    if (this.pendingId === undefined) {
      this.pendingId = this.loadOrCreate().catch((error: Error) => {
        this.pendingId = undefined;
        throw error;
      });
    }
    return this.pendingId;
  }

  private async loadOrCreate(): Promise<string> {
    const store = await preferences.getPreferences(this.context, { name: 'device_identity' });
    const saved = await store.get('device_id', '');
    if (typeof saved === 'string' && saved.length > 0) {
      return saved;
    }
    const id = util.generateRandomUUID();
    await store.put('device_id', id);
    await store.flush();
    return id;
  }
}
