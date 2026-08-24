import { ChatPage } from '../features/chat/presentation/ChatPage';
import { MePage } from '../features/me/presentation/MePage';
import { ThingsPage } from '../features/things/presentation/ThingsPage';
import { TodayPage } from '../features/today/presentation/TodayPage';

@Component
export struct AppShell {
  @State private selectedIndex: number = 0;

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
      }.tabBar(this.tabBar('今天', 0))
      TabContent() {
        ThingsPage()
      }.tabBar(this.tabBar('事务', 1))
      TabContent() {
        ChatPage()
      }.tabBar(this.tabBar('对话', 2))
      TabContent() {
        MePage()
      }.tabBar(this.tabBar('我的', 3))
    }
    .barMode(BarMode.Fixed)
    .barHeight(60)
    .onChange((index: number) => {
      this.selectedIndex = index;
    })
    .backgroundColor('#F7F9F7')
  }
}
