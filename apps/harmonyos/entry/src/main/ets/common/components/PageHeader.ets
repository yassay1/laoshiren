@Component
export struct PageHeader {
  @Prop title: string;
  @Prop subtitle: string = '';

  build() {
    Column({ space: 6 }) {
      Text(this.title)
        .width('100%')
        .fontSize(30)
        .fontWeight(FontWeight.Bold)
        .fontColor('#17251E')
      if (this.subtitle.length > 0) {
        Text(this.subtitle)
          .width('100%')
          .fontSize(15)
          .fontColor('#66756D')
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ left: 20, right: 20, top: 18, bottom: 14 })
  }
}
