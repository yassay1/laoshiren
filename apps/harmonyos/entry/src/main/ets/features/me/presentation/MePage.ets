import { PageHeader } from '../../../common/components/PageHeader';

@Component
export struct MePage {
  @Builder
  private settingRow(title: string, value: string) {
    Row() {
      Text(title).fontSize(16).fontColor('#17251E')
      Blank()
      Text(value).fontSize(14).fontColor('#718078')
    }
    .width('100%')
    .height(58)
    .padding({ left: 16, right: 16 })
  }

  build() {
    Column() {
      PageHeader({ title: '我的', subtitle: '账号、通知、隐私和开发环境' })
      Column({ space: 1 }) {
        this.settingRow('后端连接', '待配置')
        this.settingRow('通知与主动提醒', '未开启')
        this.settingRow('本地缓存', '轻量会话状态')
        this.settingRow('版本', '1.0.0 · API 24')
      }
      .margin({ left: 20, right: 20 })
      .borderRadius(16)
      .backgroundColor('#FFFFFF')
    }.width('100%').height('100%')
  }
}
