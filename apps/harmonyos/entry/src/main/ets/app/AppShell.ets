import { ClientDependencies } from '../common/ClientDependencies';
import { ChatPage } from '../features/chat/presentation/ChatPage';
import { MePage } from '../features/me/presentation/MePage';
import { TasksPage } from '../features/tasks/presentation/TasksPage';
import { ThingsPage } from '../features/things/presentation/ThingsPage';
import { TodayPage } from '../features/today/presentation/TodayPage';

@Component
export struct AppShell {
  @State private selectedIndex: number = 0;
  private readonly dependencies: ClientDependencies = ClientDependencies.shared();

  @Builder
  private tabBar(label: string, index: number) {
    Column({ space: 4 }) {
      Text(label)
        .fontSize(13)
        .fontWeight(this.selectedIndex === index ? FontWeight.Medium : FontWeight.Regular)
        .fontColor(this.selectedIndex === index ? '#22543D' : '#718096')
    }
    .width('100%')
    .height(52)
    .justifyContent(FlexAlign.Center)
  }

  build() {
    Tabs({ barPosition: BarPosition.End, index: this.selectedIndex }) {
      TabContent() {
        TodayPage()
      }.tabBar(this.tabBar('\u4ECA\u5929', 0))
      TabContent() {
        ThingsPage()
      }.tabBar(this.tabBar('\u4E8B\u52A1', 1))
      TabContent() {
        TasksPage()
      }.tabBar(this.tabBar('\u4EFB\u52A1', 2))
      TabContent() {
        ChatPage()
      }.tabBar(this.tabBar('\u5BF9\u8BDD', 3))
      TabContent() {
        MePage()
      }.tabBar(this.tabBar('\u6211\u7684', 4))
    }
    .barMode(BarMode.Fixed)
    .barHeight(60)
    .onChange((index: number) => {
      this.selectedIndex = index;
    })
    .backgroundColor('#F7F9F7')
  }
}
