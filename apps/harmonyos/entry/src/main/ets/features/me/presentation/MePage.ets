import { PageHeader } from '../../../common/components/PageHeader';
import { MeViewModel } from './MeViewModel';
import { DeviceViewModel } from './DeviceViewModel';

@Component
export struct MePage {
  @State private viewModel: MeViewModel = new MeViewModel();
  @State private deviceViewModel: DeviceViewModel = new DeviceViewModel();

  aboutToAppear(): void {
    this.viewModel.initialize();
    this.deviceViewModel.initialize();
  }

  private async signIn(): Promise<void> {
    await this.viewModel.signIn();
    if (this.viewModel.authStatus === 'AUTHENTICATED') {
      await this.viewModel.initialize();
      await this.deviceViewModel.initialize();
    }
  }

  private async signOut(): Promise<void> {
    await this.viewModel.signOut();
    this.deviceViewModel.reset();
  }

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
      PageHeader({ title: '我的', subtitle: '账号与服务状态' })
      if (this.viewModel.authStatus === 'SIGNED_OUT') {
        Text('\u672A\u767B\u5F55').fontSize(17).fontColor('#52665D').margin({ left: 20, right: 20, bottom: 8 })
        Button(this.viewModel.usesHuaweiAccount ? '华为账号登录' : '\u6A21\u62DF\u767B\u5F55')
          .onClick(() => { this.signIn(); })
          .enabled(!this.viewModel.busy && this.viewModel.backendConfigured)
          .margin({ left: 20, right: 20, bottom: 12 })
      } else if (this.viewModel.authStatus === 'SESSION_EXPIRED') {
        Text('\u4F1A\u8BDD\u5DF2\u8FC7\u671F').fontSize(17).fontColor('#9B2C2C').margin({ left: 20, right: 20, bottom: 8 })
        Button('\u91CD\u65B0\u767B\u5F55')
          .onClick(() => { this.signIn(); })
          .enabled(!this.viewModel.busy && this.viewModel.backendConfigured)
          .margin({ left: 20, right: 20, bottom: 12 })
      } else {
        Text('\u5DF2\u767B\u5F55').fontSize(17).fontColor('#276749').margin({ left: 20, right: 20, bottom: 8 })
        Button('\u9000\u51FA\u767B\u5F55')
          .onClick(() => { this.signOut(); })
          .enabled(!this.viewModel.busy)
          .margin({ left: 20, right: 20, bottom: 12 })
      }
      if (this.viewModel.errorText.length > 0) {
        Text(this.viewModel.errorText)
          .fontSize(13)
          .fontColor('#9B2C2C')
          .margin({ left: 20, right: 20, bottom: 12 })
      }
      if (this.viewModel.profile !== undefined) {
        Column({ space: 6 }) {
          Text(this.viewModel.profile.user_id).fontSize(14).fontColor('#52665D')
          Text(this.viewModel.profile.status).fontSize(18).fontColor('#183C2C')
        }.width('100%').padding(16).margin({ left: 20, right: 20 })
          .borderRadius(16).backgroundColor('#E8F3EC')
      }
      if (this.deviceViewModel.device !== undefined) {
        Text(this.deviceViewModel.device.platform)
          .width('100%').padding({ left: 20, right: 20, top: 10 })
          .fontSize(13).fontColor('#66756D')
      }
      if (this.deviceViewModel.errorText.length > 0) {
        Text(this.deviceViewModel.errorText)
          .fontSize(13)
          .fontColor('#9B2C2C')
          .margin({ left: 20, right: 20, bottom: 12 })
      }
      Column({ space: 1 }) {
        this.settingRow('后端服务', this.viewModel.backendLabel)
        this.settingRow('推送服务', this.deviceViewModel.pushStatus)
        this.settingRow('主动提醒', this.viewModel.reminderLabel)
        this.settingRow('本地缓存', '轻量会话状态')
        this.settingRow('版本', '1.0.0 · API 24')
      }
      .margin({ left: 20, right: 20 })
      .borderRadius(16)
      .backgroundColor('#FFFFFF')
    }.width('100%').height('100%')
  }
}
