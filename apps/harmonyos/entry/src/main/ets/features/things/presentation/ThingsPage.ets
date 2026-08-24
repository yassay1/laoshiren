import { PageHeader } from '../../../common/components/PageHeader';

@Component
export struct ThingsPage {
  build() {
    Column() {
      PageHeader({ title: '事务', subtitle: '现实中的事情，以服务端 Personal State 为准' })
      Column({ space: 12 }) {
        TextInput({ placeholder: '搜索事务' })
          .height(46)
          .borderRadius(14)
          .backgroundColor('#FFFFFF')
        Column({ space: 10 }) {
          Text('还没有同步事务')
            .fontSize(20)
            .fontWeight(FontWeight.Medium)
            .fontColor('#17251E')
          Text('告诉老实人你最近在做什么，它会帮助你持续跟进。')
            .fontSize(15)
            .fontColor('#66756D')
            .textAlign(TextAlign.Center)
        }.layoutWeight(1).justifyContent(FlexAlign.Center)
      }
      .width('100%')
      .layoutWeight(1)
      .padding({ left: 20, right: 20, bottom: 20 })
    }.width('100%').height('100%')
  }
}
