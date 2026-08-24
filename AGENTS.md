# 老实人项目开发约束

## 基线

- 七份 v1.0 核心设计文档是产品与技术基线。
- 工程目录和依赖方向以《老实人｜工程目录与项目架构规范 v1.0》为最高优先级实现规范。
- 重大架构变化必须先更新对应设计文档或新增 ADR。

## 后端边界

- Presentation、Agent、Worker 只能调用 Application 用例。
- Domain 不得依赖 FastAPI、LangGraph、SQLAlchemy、LLM SDK、HTTP Client 或 HarmonyOS。
- Infrastructure 实现 Application 定义的 ports；具体数据库和外部服务不得污染 Domain。
- Agent Tool 是 Adapter，必须调用 Application；禁止 Tool 直接访问 ORM、Repository 或 SQL。
- API Schema、Application DTO、Domain Entity、ORM Model 必须分开。
- 依赖组装集中在 `bootstrap.py`，`main.py` 保持轻薄。

## 数据与 Agent

- Personal State 是当前现实状态的权威来源；Memory 不得覆盖当前 State。
- Thread、Thing、Graph State、Long-term Memory、Timeline、Source、Automation 必须分离。
- 重要状态写入必须支持乐观并发、幂等、StateMutation 和 Timeline。
- Deadline 使用 `CONFIRMED / PROBABLE / UNCONFIRMED / DISPUTED`。
- Deadline 必须通过专门的 Application 用例；通用 Thing patch 不得直接覆盖正式 deadline。
- LLM 不得直接执行 SQL、访问数据库连接、文件凭据或外部服务密钥。
- 默认使用单一 Executive Agent；只有独立多步自主任务才引入 Specialist Subgraph。

## 客户端

- HarmonyOS 使用 ArkTS + ArkUI 原生开发，采用单 entry module、feature-first + MVVM。
- 客户端不复制 Agent 决策和后端业务规则。
- 客户端结构化操作与 Agent Tool 必须复用相同 Application 能力。
- Provider 密钥、数据库凭据、Push 服务端凭据不得进入客户端。

## 质量

- Domain/Application 行为必须有单元测试。
- Repository、API、Tool→Application 使用集成测试。
- Agent 行为质量放入 `backend/evals/`，不与确定性业务测试混用。
- 不以空目录、空抽象或固定多 Agent 结构制造架构复杂度。
