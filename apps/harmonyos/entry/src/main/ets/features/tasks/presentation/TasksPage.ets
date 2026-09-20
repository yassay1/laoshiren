import { PageHeader } from '../../../common/components/PageHeader';
import { Task } from '../domain/TaskModels';
import { TasksViewModel } from './TasksViewModel';

@Component
export struct TasksPage {
  @State private viewModel: TasksViewModel = new TasksViewModel();

  aboutToAppear(): void {
    this.viewModel.initialize();
  }

  build() {
    Column() {
      PageHeader({ title: 'Tasks', subtitle: 'Open tasks from Personal State' })
      if (this.viewModel.busy) {
        LoadingProgress().width(24).height(24).color('#276749')
      } else if (this.viewModel.errorText.length > 0) {
        Text(this.viewModel.errorText).fontSize(16).fontColor('#8B2F2F')
      } else if (this.viewModel.tasks.length === 0) {
        Text('No standalone tasks').fontSize(18).fontColor('#66756D')
      } else {
        List({ space: 10 }) {
          ForEach(this.viewModel.tasks, (task: Task) => {
            ListItem() {
              Row() {
                Column({ space: 4 }) {
                  Text(task.title).fontSize(17).fontColor('#17251E')
                  Text(task.due_at ?? 'No due date').fontSize(13).fontColor('#66756D')
                }.layoutWeight(1)
                Text(task.status).fontSize(13).fontColor('#276749')
              }.width('100%').padding(14).borderRadius(14).backgroundColor('#FFFFFF')
            }
          }, (task: Task) => task.id)
        }.width('100%').layoutWeight(1)
      }
    }.width('100%').height('100%').padding({ left: 20, right: 20 })
  }
}
