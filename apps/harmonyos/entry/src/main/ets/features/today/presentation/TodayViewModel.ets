import { ClientDependencies } from '../../../common/ClientDependencies';
import { TodayRepository } from '../data/TodayRepository';
import { TodaySnapshot } from '../domain/TodayModels';

@Observed
export class TodayViewModel {
  snapshot?: TodaySnapshot;
  busy: boolean = false;
  errorText: string = '';
  private readonly repository: TodayRepository;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.repository = new TodayRepository(dependencies.api);
  }

  async initialize(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.errorText = '';
    try {
      this.snapshot = await this.repository.get();
    } catch (error) {
      this.errorText = error instanceof Error ? error.message : '暂时无法加载今日状态';
    } finally {
      this.busy = false;
    }
  }
}
