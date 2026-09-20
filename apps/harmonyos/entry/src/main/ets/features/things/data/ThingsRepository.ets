import { BackendApiClient } from '../../../common/network/BackendApiClient';
import { Thing } from '../domain/ThingModels';

export class ThingsRepository {
  private readonly api: BackendApiClient;

  constructor(api: BackendApiClient) {
    this.api = api;
  }

  list(query: string = ''): Promise<Thing[]> {
    const suffix = query.trim().length === 0 ? '' : `?q=${encodeURIComponent(query.trim())}`;
    return this.api.get<Thing[]>(`/things${suffix}`);
  }
}
