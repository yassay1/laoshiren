# ADR 0001：采用 Monorepo

- 状态：Accepted
- 日期：2026-08-23

## 决策

HarmonyOS 客户端、FastAPI 后端、Agent、契约、部署与文档保存在同一 Git 仓库中。

## 原因

V1 由单人开发，一个产品能力通常同时修改 ArkTS、API、Application、Tool、数据库和契约。Monorepo 有利于原子提交、统一 CI 和接口同步。
