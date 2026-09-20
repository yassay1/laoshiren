import { BackendApiClient } from '../../../common/network/BackendApiClient';
import { Task } from '../domain/TaskModels';

export class TasksRepository {
  private readonly api: BackendApiClient;

  constructor(api: BackendApiClient) {
    this.api = api;
  }

  list(): Promise<Task[]> {
    return this.api.get<Task[]>('/tasks');
  }
}
