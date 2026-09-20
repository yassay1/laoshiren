import { BackendApiClient } from '../../../common/network/BackendApiClient';
import { UserProfile } from '../domain/MeModels';

export class MeRepository {
  private readonly api: BackendApiClient;

  constructor(api: BackendApiClient) {
    this.api = api;
  }

  getProfile(): Promise<UserProfile> {
    return this.api.get<UserProfile>('/me');
  }
}
