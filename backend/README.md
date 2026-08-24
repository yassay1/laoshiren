# Backend

FastAPI 模块化单体，使用 Python 3.12、uv、SQLAlchemy/Alembic、PostgreSQL/pgvector、LangGraph 和 PostgreSQL Checkpointer。

## 配置

复制 `.env.example` 为本地 `.env`，至少配置模型 Provider、模型名、API Base 和 Key。`.env` 被 Git 忽略，不得提交或粘贴到日志。

默认开发数据库：`postgresql+asyncpg://laoshiren:laoshiren@localhost:5432/laoshiren`。

## 初始化

```powershell
uv sync
uv run alembic upgrade head
```

本地 PostgreSQL/pgvector 配置位于 `../deploy/compose/docker-compose.dev.yml`。

## 启动

Windows 必须使用项目入口，确保 psycopg 异步连接运行在 SelectorEventLoop：

```powershell
$env:PYTHONPATH='src'
uv run python -m laoshiren
```

服务监听 `http://127.0.0.1:8000`，API 前缀 `/api/v1`。当前认证仅为开发 Bearer Token。

## 验证

```powershell
uv run ruff check .
uv run mypy
uv run pytest -m "not live_model"

$env:RUN_DATABASE_TESTS='1'
uv run pytest -m "not live_model"
```

真实模型评测默认不会运行：

```powershell
$env:RUN_LIVE_MODEL_EVALS='1'
uv run pytest evals -m live_model
```

## 目录职责

- `src/laoshiren/domain/`：无框架领域实体、值对象和状态机。
- `src/laoshiren/application/`：用例、DTO、ports 和事务边界。
- `src/laoshiren/infrastructure/`：SQLAlchemy、对象存储、模型 Provider、Checkpointer 和调度适配器。
- `src/laoshiren/presentation/`：FastAPI 路由、API Schema、认证依赖和错误映射。
- `src/laoshiren/agent/`：Executive Graph、Tool Registry、Policy 和模型契约。
- `src/laoshiren/workers/`：Agent Run 与 Automation 后台入口。
- `migrations/`：业务数据库 Alembic 迁移；LangGraph checkpoint 表由框架 lifecycle 管理。
- `tests/`：确定性 unit/integration 测试。
- `evals/`：显式开启的真实模型质量验证。

详细能力和已知风险见 `../docs/CURRENT_IMPLEMENTATION.md`。
