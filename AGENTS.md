# 老实人项目开发约束

## 开发基线

- Backend V2.2 的最高优先级基线是仓库根目录七份正式 v2.2 设计文档；导航见 README。
- 若通用设计与领域专项设计冲突且没有更新版本明确覆盖，以领域专项设计为准。
- Automation / Scheduler / Notification 以《老实人_Automation_Scheduler_Notification技术设计_v2.2》为 authoritative source。
- README、CURRENT_IMPLEMENTATION 只描述导航和当前实现，不得反向覆盖正式设计。
- 重大架构或冻结 Contract 变化必须先更新正式设计或新增 ADR。

## 依赖与工程规则

- 依赖方向固定为 Presentation / Agent / Worker → Application → Domain。
- Infrastructure 只实现 Application ports；Domain 不得依赖 FastAPI、LangGraph、SQLAlchemy、模型 SDK、HTTP Client 或 HarmonyOS。
- Agent Tool 是 Adapter，只能调用 Application Use Case，禁止直接访问 ORM、Repository 或 SQL。
- API Schema、Application DTO、Domain Entity、ORM Model 必须分离。
- 依赖组装集中在 backend/src/laoshiren/bootstrap.py；main.py 保持轻薄。
- PostgreSQL 是 durable truth；Redis 只允许 non-authoritative cache、coordination、rate limit 与 wake-up。
- LangGraph 只负责 Agent Runtime / orchestration；checkpoint identity 使用 run_id。
- Personal State 是 current reality authority；Memory、Thread、File、Evidence 不得覆盖当前 State。
- 重要 mutation 使用 version / expected_version；禁止 silent last-write-wins。
- Tool 使用 stable action_id、ToolExecution Ledger、幂等 replay 与 UNKNOWN_OUTCOME 语义。
- 不使用长时间 LangGraph wait 实现 Automation；未来工作必须进入 PostgreSQL durable work。
- 不引入 LangSmith、Temporal、Kafka、Elasticsearch、独立 Vector DB、新微服务或固定多 Agent 网络。
- 不提前实现正式设计明确 Deferred 的能力。

## 数据与通知

- Deadline certainty 固定为 CONFIRMED / PROBABLE / UNCONFIRMED / DISPUTED，并通过专门 Application 用例修改。
- File 使用稳定内部 file_id；Provider file ID、对象 URL 和签名 URL 不能作为业务主键。
- Notification 不新增独立 NotificationOutbox；采用 NotificationIntent + NotificationDelivery + DurableJob。
- Device 只保存设备身份及 platform、timezone、last_seen 等设备级信息；Push Token 属于独立 PushEndpoint。
- Automation 通知类型为 REMINDER / CONDITION_MET / CONDITION_WATCH_ENDED。

## 质量与命令

- Domain/Application 行为写单元测试；Repository、API、Tool→Application 写集成测试；Agent 质量测试放 backend/evals。
- 数据库变更必须提供可升级、可降级 Alembic migration。
- 每个 Phase 检查 OpenAPI、Tool Schema、SSE Schema 和 DB Contract drift。

常用命令（PowerShell）：

```powershell
cd backend
uv sync --locked
uv run ruff check .
uv run mypy
uv run pytest tests/unit tests/evals -m "not live_model"
$env:RUN_DATABASE_TESTS='1'
uv run pytest -m "not live_model"
uv run alembic upgrade head
uv run python scripts/export_openapi.py
uv run python scripts/export_tool_registry.py
$env:PYTHONPATH='src'
uv run python -m laoshiren
```
