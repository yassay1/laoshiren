import { ClientDependencies } from '../../../common/ClientDependencies';
import { TasksRepository } from '../data/TasksRepository';
import { Task } from '../domain/TaskModels';

@Observed
export class TasksViewModel {
  tasks: Task[] = [];
  busy: boolean = false;
  errorText: string = '';
  private readonly repository: TasksRepository;

  constructor(dependencies: ClientDependencies = ClientDependencies.shared()) {
    this.repository = new TasksRepository(dependencies.api);
  }

  async initialize(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.errorText = '';
    try {
      this.tasks = await this.repository.list();
    } catch (error) {
      this.errorText = error instanceof Error ? error.message : '暂时无法加载任务';
    } finally {
      this.busy = false;
    }
  }
}
