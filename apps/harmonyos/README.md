# HarmonyOS Client

本目录是可编译的 ArkTS + ArkUI Stage Model 应用，采用单 `entry` module、feature-first + MVVM。

## 已验证基线

- bundleName：`com.caonan.campusagent`
- DevEco Studio：本机实际使用 6.1.1.300
- compile/target SDK：HarmonyOS 6.1.1(24) / API 24
- compatible SDK：HarmonyOS 5.0.0(12)
- 模拟器：`CampusAgent_API24`，Pura 90 Pro，x86_64，API 24
- Hvigor：6.24.4

源码权威位置是当前目录。Hvigor 会拒绝中文真实路径，因此本机验证时把源码机械同步到 `D:\proj\campusagent-harmony-build` 后构建；该镜像不属于仓库，也不是第二份源码。

## 当前实现

- `AppShell.ets`：Today / Things / Chat / Me 四栏导航。
- `features/chat/`：真实 Thread 创建、Run 提交、SSE 消费、消息刷新、错误重试和等待确认 UI。
- `common/network/ApiClient.ets`：当前集中使用 `http://127.0.0.1:8000/api/v1` 和开发令牌。
- Today、Things、Me：目前是静态产品壳，尚未接入后端 Product API。

模拟器联调需要将设备端 8000 端口反向转发到宿主机后端。开发期 `network_config.json` 允许明文 HTTP；发布前必须改为 HTTPS 并移除全局明文放行。

## 已知限制

- Chat 初始化时总是创建新 Thread，没有历史列表、选中会话持久化或前台恢复。
- 当前只支持文本输入，没有 Source 附件、Picker、Share、STT、Push 或深链。
- 确认/拒绝请求的 response 字段与后端 Graph 当前契约不一致，这是待修复缺陷，不应视为 HITL 已完整可用。
- Base URL 与开发 Token 仍硬编码；只适合本地开发。
- 客户端没有自动化测试目录，当前验证依赖 ArkTS 编译、HAP 打包和模拟器人工闭环。

任何模型 Provider Key、数据库凭据、AGC/Push 服务端凭据和 Release 签名材料都不得进入客户端。
