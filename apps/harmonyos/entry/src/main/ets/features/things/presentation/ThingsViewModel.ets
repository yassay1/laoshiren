import { ClientDependencies } from '../../../common/ClientDependencies';
import { ThingsRepository } from '../data/ThingsRepository';
import { Thing } from '../domain/ThingModels';

@Observed
export class ThingsViewModel {
  things: Thing[] = [];
  query: string = '';
  busy: boolean = false;
  errorText: string = '';
  private readonly repository: ThingsRepository;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.repository = new ThingsRepository(dependencies.api);
  }

  async initialize(): Promise<void> {
    if (!this.busy) await this.refresh();
  }

  async search(): Promise<void> {
    await this.refresh();
  }

  private async refresh(): Promise<void> {
    this.busy = true;
    this.errorText = '';
    try {
      this.things = await this.repository.list(this.query);
    } catch (error) {
      this.errorText = error instanceof Error ? error.message : '暂时无法加载事务';
    } finally {
      this.busy = false;
    }
  }
}
