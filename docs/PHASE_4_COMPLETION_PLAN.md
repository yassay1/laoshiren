# Phase 4 Completion Plan

目标：完成 Backend V2.2 File 与 Evidence 迁移，建立稳定 `file_id` 资产、ProcessingGeneration、RetrievalSegment、WebObservation、MessageAttachment 与 typed EvidenceRef，并逐步从 legacy Source 切到 V2 retrieval。

设计权威：《老实人_File_Multimodal_Search_Evidence技术设计_v2.2.md》。

## P4.1 — Expand

状态：**完成**

## P4.2 — Backfill Verification

状态：**完成**（`test_file_phase4.py::test_file_backfill_matches_source_identity`）

## P4.3 — MessageAttachment

状态：**完成**（`POST /sources?message_id=` + ContextAssembler `attachment_context`）

## P4.4 — WebObservation Promotion

状态：**完成**（`url_inspect` + `persist_observation` + `evidence_ref`）

## P4.5 — Switch Retrieval

状态：**完成**

## P4.6 — Physical Purge and Orphan Scanner

状态：**完成**（`FILE_PURGE` DurableJob + `FilePurgeWorker` + storage orphan scan）

## Phase 4 Exit Criteria（全部满足）

1. V2 File 表与 legacy Source 双写/backfill。
2. `file_search`/`file_inspect` 优先 `retrieval_segments`。
3. MessageAttachment 进入 invocation-time context。
4. typed `EvidenceRef` 写入 deadline mutation 与 WebObservation promotion。
5. 逻辑删除与物理 purge 分离（`FILE_PURGE` job）。
6. integration 测试覆盖 backfill 与 purge。

## 明确 Deferred（Phase 5+）

- 完整 multimodal AttachmentRepresentationSelector / provider native vision
- Memory DurableJob formation
- cross-encoder reranker / RRF 调优
- account deletion fence 全链路
