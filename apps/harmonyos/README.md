# HarmonyOS Client

本目录是 ArkTS + ArkUI Stage Model 应用，采用单 `entry` module、feature-first + MVVM。

## 工程基线

- Bundle Name：`com.yenan.laoshiren`
- DevEco Studio：6.1.1.300；target SDK：HarmonyOS 6.1.1(24)
- compatible SDK：HarmonyOS 5.0.0(12)
- 运行时配置入口：`entry/build-profile.json5` 的 `buildOptionSet` / `buildModeBinder`

## Debug 与 Release

`EntryAbility` 在启动时初始化 `ClientDependencies`。运行模式和 API 地址来自 Hvigor 生成的 `BuildProfile`，没有运行时默认回退。

| 模式 | 后端地址 | 认证 | 推送 | 主动提醒 |
| --- | --- | --- | --- | --- |
| Debug | 本地 `http://127.0.0.1:8000/api/v1` | Mock | Mock | Mock（当前无业务调用） |
| Release | `backendApiUrl`，当前为空 | Huawei Account | Huawei Push | 不可用 |

Release 的 `backendApiUrl` 必须配置为真实的非本机 HTTPS API 根地址。当前留空是明确的发布阻塞项：应用会显示“未配置 HTTPS 服务地址”，网络请求会报错，不会连接本机地址或切换到 Mock。填入地址后，用 `devecocli build --product default --build-mode release` 构建，并检查最终 APP。

设备 ID 通过 ArkData Preferences 持久化，在同一次安装内复用。提醒当前没有真实实现，也没有业务调用；Release 明确关闭。`MePage` 根据运行时配置、推送令牌上传结果显示状态。

## 发布前仍需验证

1. 配置真实 HTTPS 后端地址，并在真机上验证连接与会话接口。服务端的 Huawei Account 集成必须使用真实模式，不能保持 stub。
2. `entry/src/main/module.json5` 已填写先前确认的应用级 Account Kit `client_id`。仍需核对它与 AGC 应用凭据一致、发布证书身份有效、Push Kit 已开通，并用真机验证授权码交换、Push Token 获取和上传。当前工程没有 `agconnect-services.json`；应按所使用的 HarmonyOS SDK 官方接入要求核对是否需要该文件或其他应用配置。
3. 全局 `network_config.json` 不再允许明文流量。Debug 若仍需通过 HTTP 联调，应使用单独的开发设备配置；Release 只接受 HTTPS。
4. Release 混淆仍关闭。先完成账号、推送和关键业务的真机回归，再决定是否开启并补齐规则。
5. `Chat` 的历史会话、附件、HITL 等仍有功能限制；这些事项与本次运行时配置分开跟踪。

构建和签名成功只证明包可生成，不代表上述服务已通过真机验证或可提交 AGC。
