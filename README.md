# 老实人

“老实人”是一个以 Personal State 为现实状态权威源、以单一 Executive Agent 为默认决策入口的 HarmonyOS 个人事务智能体项目。

当前仓库已经不是初始化骨架：后端已具备 Personal State、Source、Memory、Automation/Attention、Thread/Run/SSE、LangGraph Executive Agent 和 DeepSeek/智谱适配器；HarmonyOS 客户端已完成可安装的四入口应用壳，并跑通 Chat → Run → Agent → Assistant Message 的模拟器闭环。

## 当前权威说明

- [当前实现与审核说明](docs/CURRENT_IMPLEMENTATION.md)：以实际代码为准的能力、调用链、缺口和风险。
- [后端说明](backend/README.md)：启动、配置、迁移和测试命令。
- [HarmonyOS 客户端说明](apps/harmonyos/README.md)：实际工程、构建限制和当前页面完成度。
- `老实人_*_v1.0.txt`：七份产品与技术设计基线。它们描述目标架构，不等同于当前全部实现。
- [HarmonyOS 官方资源调研](docs/research/HarmonyOS_Official_Resources_Research.txt)：平台能力研究资料，不是当前功能完成清单。

## 主要目录

```text
apps/harmonyos/       ArkTS + ArkUI Stage Model 客户端
backend/              FastAPI 模块化单体、业务核心、Agent 与 Worker
contracts/            OpenAPI 快照与 SSE 事件 JSON Schema
deploy/               PostgreSQL/pgvector 本地开发配置
docs/                 ADR、当前实现说明和研究资料
```

后端依赖方向：

```text
Presentation / Agent / Worker
             ↓
         Application
             ↓
           Domain

Infrastructure 实现 Application ports，bootstrap.py 负责组装。
```

## 快速验证

后端要求 Python 3.12、uv、PostgreSQL 17 + pgvector。详细步骤见 [backend/README.md](backend/README.md)。

```powershell
cd backend
uv sync
uv run ruff check .
uv run mypy
$env:RUN_DATABASE_TESTS='1'
uv run pytest -m "not live_model"
```

Windows 启动入口：

```powershell
$env:PYTHONPATH='src'
uv run python -m laoshiren
```

## 重要限制

- 当前是固定开发令牌和固定开发用户，不是正式账号体系。
- Run 调度使用进程内队列；服务重启不会自动扫描并恢复数据库中的 QUEUED Run。
- HarmonyOS Chat 每次 ViewModel 初始化都会新建 Thread，尚未实现历史会话恢复。
- Today、Things、Me 目前主要是展示壳，尚未接入对应 Product API。
- 客户端与后端的确认载荷存在已知不一致，详见当前实现说明。
- 开发期客户端使用本地 HTTP 和 `change-me` 令牌；生产必须改为 HTTPS、正式认证和环境化配置。

Provider API Key 只允许保存在被忽略的 `backend/.env`，不得进入代码、客户端或文档。
