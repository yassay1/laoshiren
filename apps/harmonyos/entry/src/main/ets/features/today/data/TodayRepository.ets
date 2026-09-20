import { BackendApiClient } from '../../../common/network/BackendApiClient';
import { TodaySnapshot } from '../domain/TodayModels';

export class TodayRepository {
  private readonly api: BackendApiClient;

  constructor(api: BackendApiClient) {
    this.api = api;
  }

  get(): Promise<TodaySnapshot> {
    return this.api.get<TodaySnapshot>('/today');
  }
}
