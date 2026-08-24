import { PageHeader } from '../../../common/components/PageHeader';

@Component
export struct TodayPage {
  build() {
    Scroll() {
      Column({ space: 14 }) {
        PageHeader({ title: '今天', subtitle: '把注意力放在真正需要推进的事情上' })
        Column({ space: 12 }) {
          Row() {
            Text('现在最值得关注').fontSize(14).fontColor('#496457')
            Blank()
            Text('等待同步').fontSize(12).fontColor('#7A8A82')
          }.width('100%')
          Text('连接后端后，这里会展示临近截止、阻塞事项和 Agent 建议。')
            .width('100%')
            .fontSize(20)
            .fontWeight(FontWeight.Medium)
            .fontColor('#183C2C')
          Button('开始和老实人聊聊')
            .type(ButtonType.Capsule)
            .fontColor('#FFFFFF')
            .backgroundColor('#276749')
        }
        .margin({ left: 20, right: 20 })
        .padding(20)
        .borderRadius(20)
        .backgroundColor('#E8F3EC')
        Text('最近进展')
          .width('100%')
          .padding({ left: 20, right: 20, top: 8 })
          .fontSize(19)
          .fontWeight(FontWeight.Bold)
          .fontColor('#17251E')
        Text('完成客户端与后端联调后，状态变化会显示在这里。')
          .margin({ left: 20, right: 20 })
          .padding(18)
          .width('calc(100% - 40vp)')
          .fontSize(15)
          .fontColor('#66756D')
          .borderRadius(16)
          .backgroundColor('#FFFFFF')
      }.width('100%').padding({ bottom: 24 })
    }.width('100%').height('100%')
  }
}
