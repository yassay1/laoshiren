import { PageHeader } from '../../../common/components/PageHeader';
import { ChatMessage } from '../domain/ChatModels';
import { ChatViewModel } from './ChatViewModel';

@Component
export struct ChatPage {
  @State private viewModel: ChatViewModel = new ChatViewModel();

  aboutToAppear(): void {
    this.viewModel.initialize();
  }

  aboutToDisappear(): void {
    this.viewModel.close();
  }

  @Builder
  private messageBubble(message: ChatMessage) {
    Row() {
      Text(message.content)
        .fontSize(16)
        .fontColor(message.role === 'USER' ? '#FFFFFF' : '#183C2C')
        .lineHeight(24)
        .padding(16)
        .borderRadius(18)
        .backgroundColor(message.role === 'USER' ? '#276749' : '#E8F3EC')
        .constraintSize({ maxWidth: '84%' })
    }
    .width('100%')
    .justifyContent(message.role === 'USER' ? FlexAlign.End : FlexAlign.Start)
  }

  @Builder
  private emptyState() {
    Column({ space: 10 }) {
      Text('你好，我是老实人')
        .fontSize(20)
        .fontWeight(FontWeight.Medium)
        .fontColor('#183C2C')
      Text('把正在发生的事告诉我，我会帮你理清信息、判断下一步并持续推进。')
        .fontSize(15)
        .fontColor('#52665D')
        .lineHeight(23)
        .textAlign(TextAlign.Center)
    }
    .width('100%')
    .padding({ left: 28, right: 28, top: 52, bottom: 24 })
  }

  build() {
    Column() {
      PageHeader({ title: '老实人', subtitle: '把信息、判断和行动连起来' })
      Scroll() {
        Column({ space: 14 }) {
          if (this.viewModel.messages.length === 0 && !this.viewModel.busy) {
            this.emptyState()
          }
          ForEach(this.viewModel.messages, (message: ChatMessage) => {
            this.messageBubble(message)
          }, (message: ChatMessage) => message.id)
          if (this.viewModel.statusText.length > 0) {
            Row({ space: 8 }) {
              LoadingProgress().width(18).height(18).color('#276749')
              Text(this.viewModel.statusText).fontSize(14).fontColor('#52665D')
            }
            .width('100%')
            .padding({ left: 4, top: 4 })
          }
          if (this.viewModel.waitingRun !== undefined) {
            Column({ space: 12 }) {
              Text('这一步需要你的确认')
                .fontSize(16)
                .fontWeight(FontWeight.Medium)
                .fontColor('#183C2C')
              Text('确认后我会继续执行；拒绝则停止这一步。')
                .fontSize(14)
                .fontColor('#52665D')
              Row({ space: 10 }) {
                Button('拒绝')
                  .height(48).layoutWeight(1)
                  .fontColor('#8B2F2F').backgroundColor('#FCE8E8')
                  .onClick(() => this.viewModel.respondToInterrupt(false))
                Button('确认继续')
                  .height(48).layoutWeight(1)
                  .fontColor('#FFFFFF').backgroundColor('#276749')
                  .onClick(() => this.viewModel.respondToInterrupt(true))
              }
            }
            .width('100%').padding(16).borderRadius(18).backgroundColor('#FFF6DD')
          }
          if (this.viewModel.errorText.length > 0) {
            Row({ space: 10 }) {
              Text(this.viewModel.errorText)
                .layoutWeight(1).fontSize(14).fontColor('#8B2F2F')
              Button('重试')
                .height(48).fontColor('#8B2F2F').backgroundColor('#FCE8E8')
                .onClick(() => this.viewModel.retry())
            }
            .width('100%')
            .padding({ left: 14, right: 8, top: 6, bottom: 6 })
            .borderRadius(14).backgroundColor('#FFF2F2')
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .padding({ left: 18, right: 18, top: 8, bottom: 12 })
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      Row({ space: 10 }) {
        TextInput({ text: this.viewModel.draft, placeholder: '输入消息…' })
          .layoutWeight(1).height(48).borderRadius(18).backgroundColor('#FFFFFF')
          .onChange((value: string) => {
            this.viewModel.draft = value;
          })
          .onSubmit(() => this.viewModel.send())
        Button('发送')
          .enabled(this.viewModel.draft.trim().length > 0 && !this.viewModel.busy)
          .height(48).fontColor('#FFFFFF').backgroundColor('#276749')
          .onClick(() => this.viewModel.send())
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 10, bottom: 12 })
      .backgroundColor('#F1F5F2')
    }
    .width('100%').height('100%')
  }
}
