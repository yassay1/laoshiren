# 老实人

“老实人”是面向 HarmonyOS 的个人 Agent：用户用自然语言表达现实目标、信息、行动、资料、纠错和未来要求，Single Executive 负责开放式语义理解，Backend 负责将结果安全、持久、可追溯、可恢复地落到现实。

当前处于 Backend V2.2 **Phase 0–8 核心完成**阶段。真实现状见 [CURRENT_IMPLEMENTATION](docs/CURRENT_IMPLEMENTATION.md)，剩余生产化差距见 [Gap List](docs/CURRENT_V2_2_GAP_LIST.md)，发布前 Gate 见 [RELEASE_FREEZE_GATES](docs/RELEASE_FREEZE_GATES.md)。

## V2.2 正式设计导航

以下七份文档是 Backend V2.2 的最高优先级开发基线：

1. [Backend V2 总体架构](老实人_Backend_V2_总体架构设计_v2.2_正式基线版.md)
2. [Agent Runtime](老实人_Agent_Runtime技术设计_v2.2.md)
3. [Tool / API / Policy](老实人_Tool_API_Policy技术设计_v2.2.md)
4. [Personal State 与 Memory](老实人_Personal_State与Memory技术设计_v2.2.md)
5. [File / Multimodal / Search / Evidence](老实人_File_Multimodal_Search_Evidence技术设计_v2.2.md)
6. [Automation / Scheduler / Notification](老实人_Automation_Scheduler_Notification技术设计_v2.2.md)
7. [上线最小用户与通知支持](老实人_上线最小用户与通知支持设计_v2.2.md)

领域专项设计优先于同版本通用设计。Automation、Scheduler、Notification 以第 6 份文档为 authoritative source。

## 技术栈与目录

- Backend：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL 17、pgvector、Redis、LangGraph、PostgreSQL Checkpointer、uv。
- Client：HarmonyOS ArkTS + ArkUI Stage Model。
- Object Storage：当前为本地文件 Adapter；V2.2 目标保持 Port/Adapter 边界。
- Model/Search：DeepSeek/智谱和 Tavily Adapter；业务层保持 provider-neutral。

```text
apps/harmonyos/       HarmonyOS 客户端
backend/              模块化单体、Agent Runtime 与 Workers
contracts/            OpenAPI snapshot 与 SSE JSON Schema
deploy/               PostgreSQL/pgvector、Redis 本地开发配置
docs/                 当前实现、Gap、阶段、ADR、发布 Gate 与研究资料
```

后端依赖方向：

```text
Presentation / Agent / Worker → Application → Domain
Infrastructure implements Application ports
```

## 本地启动与验证

先启动 PostgreSQL/pgvector 与 Redis（需要 Docker Desktop）：

```powershell
docker compose -f deploy/compose/docker-compose.dev.yml up -d
cd backend
uv sync --locked
uv run alembic upgrade head
$env:PYTHONPATH='src'
uv run python -m laoshiren
```

服务默认监听 http://127.0.0.1:8000，API 前缀为 /api/v1。开发环境可使用固定 Bearer Token；生产应使用 Huawei 登录 Session（见 Phase 7 API）。

质量验证：

```powershell
cd backend
uv run ruff check .
uv run mypy
uv run python scripts/check_contract_schemas.py
$env:RUN_DATABASE_TESTS='1'
uv run python scripts/run_freeze_gates.py
uv run pytest -m "not live_model"
uv run python scripts/export_openapi.py
```

Provider Key 只允许保存在被忽略的 backend/.env 或正式 Secret Store，不得进入代码、客户端、日志或文档。
