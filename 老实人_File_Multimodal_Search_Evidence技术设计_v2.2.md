# 老实人 File / Multimodal / Search / Evidence 技术设计 v2.2

> **文档状态：正式开发专项基线（Baseline）**  
> **版本：v2.2**  
> **适用范围：老实人 Backend V2.2**  
> **目标平台：HarmonyOS App + Single Executive Agent**  
> **权威持久化：PostgreSQL + Object Storage**  
> **语义检索：PostgreSQL + pgvector**  
> **Redis：non-authoritative cache / coordination / wake-up only**  
> **本文不包含：最终 SQL DDL、最终 OpenAPI、具体 OCR/Parser/Embedding 参数、最终对象存储供应商配置**

---

# 0. 文档目的

本文正式冻结老实人 Backend V2.2 的 File、Attachment、Multimodal、Historical Retrieval、Web Search、URL Inspect、Evidence、Deletion、Retention、Orphan、Failure 与 Migration 设计。

核心问题只有一句话：

> **用户发来的资料、当前附件、历史材料、网页和外部搜索结果，在一个真实上线的个人 Agent 中到底是什么；它们如何被当前模型理解、以后重新找到、作为 Evidence 支持现实状态，又怎样在用户删除时真正被清理，而不把整个 Backend 变成重型 RAG / 文档管理平台。**

---

# 1. 上位架构约束

本文继承：

1. 《老实人_Backend_V2_总体架构设计_v2.2_正式基线版》
2. 《老实人_Agent_Runtime技术设计_v2.2》
3. 《老实人_Personal_State与Memory技术设计_v2.2》
4. 《老实人_Tool_API_Policy技术设计_v2.2》

关键边界：

```text
Single Executive

LangGraph State
≠ Personal State
≠ Memory
≠ File

Personal State
= 当前现实 authority

File
= 原始资料资产

Memory
= 跨 Thread 长期有价值的知识

Evidence
= 某个事实/判断为什么成立的来源引用

Observation
≠ Current Reality

Search Result
≠ Personal State

PostgreSQL
= durable metadata/state truth

Object Storage
= durable raw bytes

Redis
= non-authoritative cache / coordination

Provider file_id
≠ internal file_id
```

---

# 2. V2.2 明确不做

本专项不引入：

- Universal Source Domain；
- Elasticsearch / OpenSearch；
- 独立 Vector DB；
- Knowledge Graph；
- 所有内容统一 chunk；
- 所有 File 强制 embedding；
- 所有图片 OCR + Caption + Embedding；
- 所有 PDF 固定 chunk size；
- 所有 File 自动 LLM Summary；
- Provider Files API 作为内部 File identity；
- Search Result = State；
- Official source = automatic authority；
- Universal Evidence Entity；
- FactEvidence 知识图谱；
- Generic `file_references` 作为全系统关系 truth；
- 实时 `durable_reference_count`；
- 视频抽帧 / scene detection / video embedding pipeline；
- Browser Automation / CAPTCHA / anti-bot bypass 平台；
- 企业级 Malware Platform；
- Kafka / Temporal 仅为 File Processing 引入；
- File Delete 自动撤销 Personal State。

---

# 3. 五个核心对象边界

```text
File
= 原始资料资产

Observation
= 系统在某次读取中看到了什么

EvidenceRef
= durable fact 指向一个可定位来源

Memory
= 从过去信息中蒸馏出的长期知识

Personal State
= 用户当前现实
```

因此：

```text
File
≠ Observation
≠ Evidence
≠ Memory
≠ Personal State
```

---

# 4. File 正式定义

> **File = 老实人实际持有原始 bytes、拥有稳定 internal `file_id`、独立于 Message/Thread/Model Provider 生命周期的用户私有资料资产。**

只有系统真正持有原始资产 bytes 时才建立 File。

| 输入 | 创建 File | 说明 |
|---|---:|---|
| 上传 PDF | 是 | 原始文件资产 |
| 图片 / 拍照 | 是 | 原始媒体资产 |
| DOCX/TXT/MD/XLSX | 是 | 原始文件资产 |
| Audio File | 是 | 音频资料 |
| Video File | 是 | 允许存储，语义理解 Deferred |
| 系统实际生成并保存的 PDF/图片 | 是 | 系统持有 bytes |
| Voice Input | 默认否 | STT → Message |
| Chat 粘贴长文本 | 默认否 | Message content |
| URL | 否 | Message/Web reference |
| Search Result | 否 | Runtime Observation |
| Tool Result | 否 | Runtime Result |
| Memory | 否 | Long-term knowledge |

用户贴 PDF URL 时，只有在明确要求“保存”且系统实际下载并持久化 bytes 后，才从 Web 资源转换成 File。

---

# 5. Stable File Identity

`file_id` MUST 是老实人自己生成和管理的稳定 ID。

以下都不能作为业务 identity：

```text
OpenAI file_id
Anthropic file_id
Gemini file name / URI
Object Storage URL
signed URL
local temp path
provider request ID
```

File raw bytes 创建后不可原地替换。新版本资料创建新 File。

同 SHA-256 也不等于同一 File identity；V2.2 不提前做 physical blob dedup。

---

# 6. File Core Metadata 与 Storage Boundary

逻辑字段：

```text
file_id
owner_user_id
original_filename?
validated_mime_type
media_kind
size_bytes
content_sha256
storage_key
asset_status
version
created_at
deleted_at?
purged_at?
```

`media_kind`：

```text
IMAGE
DOCUMENT
AUDIO
VIDEO
OTHER
```

Derived metadata 如 `width / height / page_count / duration / language / parser_version / embedding_model` 不进入 File core identity。

存储边界：

```text
PostgreSQL
= File metadata / ownership / lifecycle / references

Object Storage
= raw bytes / large binary derivatives
```

---

# 7. Upload Commit Point

推荐流程：

```text
1. Backend 分配 file_id / upload session
2. bytes 写入 Object Storage pending key
3. verify object exists
4. 校验 size / MIME / signature / limits
5. PostgreSQL transaction:
   INSERT File ACTIVE
   create File Processing DurableJob
   COMMIT
6. Redis wake-up
```

真正 File commit point：

> **raw bytes 已确认存在 + PostgreSQL File row COMMIT。**

如果 Object Storage 成功但 DB transaction 失败，只留下 pending object，后续由 Temporary Upload GC 清理。

---

# 8. File Asset Lifecycle

File 业务生命周期保持最小：

```text
ACTIVE
DELETED
```

不把 `PROCESSING / READY / FAILED / PURGING` 混入 File lifecycle。

```text
DELETED + purged_at IS NULL
= 用户已经不可访问，后台仍在物理清理

DELETED + purged_at IS NOT NULL
= 原件和派生内容已清理完成
```

---

# 9. Current Attachment 与 Historical Retrieval 双路径

```text
CURRENT ATTACHMENT
→ current Model Context

HISTORICAL FILE
→ file_search
→ candidate
→ file_inspect
```

当前刚上传附件不应该：

```text
upload
→ parse
→ chunk
→ embedding
→ retrieval
→ 再给同一个模型
```

因为当前附件本身就是用户这一轮输入的一部分。

---

# 10. Current Attachment 正式路径

```text
HarmonyOS
↓
Upload / File Finalize
↓
File
↓
MessageAttachment
↓
Message
↓
Run
↓
turn_attachment_refs
↓
ModelContextAssembler
↓
AttachmentRepresentationSelector
↓
ModelGateway
↓
Provider Adapter
↓
Model
```

Persistent Message / LangGraph Checkpoint 只保存 `file_id refs`，不保存几十 MB base64 / PDF bytes。

---

# 11. ModelContextAssembler

职责只有：

```text
fetch
select
budget
format
multimodal assembly
```

它不是新 Agent，也不做业务语义判断。

内部保持 Provider-neutral：

```text
AttachmentContent
file_id
media_kind
selected_representation
mime_type
content_or_ref
```

再由 ModelGateway 适配 OpenAI / Anthropic / Gemini。

---

# 12. Representation Selection

AttachmentRepresentationSelector 根据：

```text
File
Current user question
Provider capabilities
Context budget
Available representations
Security constraints
```

选择最合适的一种或少数组合 representation。

禁止把：

```text
raw PDF
parsed text
summary
all chunks
all page images
```

全部一起塞入模型。

---

# 13. Current Attachment Priority

## Image

优先 original/safely resized image → native vision。OCR 不是当前回答前置条件。

## PDF

Provider native PDF/document 支持且 budget 允许时，优先 raw PDF direct；否则使用 selected parsed pages/text。

## DOCX

依赖老实人自己的 basic extraction fallback，Provider native capability 只能作为优化。

## XLSX

LIMITED：basic sheet/table representation。

## Audio

Provider 支持 direct audio 时 MAY direct；provider-neutral baseline 是 transcription。

## Video

V2.2 只保证上传/存储/下载，不承诺 semantic understanding。

---

# 14. Current Attachment 不等待完整 Processing

正式原则：

> **Current Attachment MUST NOT 默认等待 OCR / retrieval segmentation / embedding / summary。**

只要 File durable、当前 representation 可用、安全和 budget 允许，就可以启动当前 Run。

---

# 15. File Processing

Processing 不是当前模型请求的前置流水线。

```text
File ACTIVE
  │
  ├──→ Current Model
  │
  └──→ Durable File Processing
```

执行复用：

```text
PostgreSQL DurableJob
+
Worker claim
+
lease
+
retry/backoff
+
Recovery Scanner
+
Redis wake-up
```

---

# 16. Processing 默认范围

## Document

```text
basic metadata
text extraction
source locator mapping
```

PDF 保留 page mapping；DOCX 保留 heading/paragraph structure；XLSX 保留 sheet/table region。

## Image

默认 width/height/MIME。Text-heavy Screenshot 后台 OCR。普通照片不默认 Caption/Embedding。

## Audio

basic metadata + transcript。

## Video

basic metadata only。

因此：

```text
processing failed
≠ File unusable
```

---

# 17. ProviderArtifact

Provider upload-once/use-many artifact 只是 Adapter cache：

```text
internal_file_id
provider
provider_artifact_id
expires_at?
```

Provider artifact 过期：

```text
ObjectStorage.get(file_id)
↓
re-upload
↓
new ProviderArtifact
```

File identity 不变。

---

# 18. V2.2 Multimodal Support Matrix

| 类型 | 状态 | 当前轮 | 历史检索 |
|---|---|---|---|
| Text Message | FULL | text | Message/Memory |
| TXT/MD | FULL | direct/text | lexical + vector |
| Image/Photo | FULL current / LIMITED historical semantic | native vision | metadata |
| Screenshot | FULL | native vision | OCR + hybrid |
| PDF | FULL | native PDF优先 | extracted text + segments |
| DOCX | FULL text semantics | extraction/provider | structured text |
| XLSX | LIMITED | basic table | sheet/region |
| Voice Input | FULL input | STT → Message | 默认无 File |
| Audio File | LIMITED | direct MAY / transcript | transcript |
| Video File | UPLOAD-ONLY | semantic Deferred | metadata only |
| URL | FULL external read | url_inspect | WebObservation when durable |
| Web Search | FULL discovery | search_web | runtime only |

---

# 19. Historical Retrieval

正式采用：

```text
file_search
↓
File candidates
↓
file_inspect
↓
bounded relevant context
```

不依赖 Thread history，也不建设统一“知识库 ingestion”。

---

# 20. Source Representation 与 Retrieval Representation

Source Representation：

```text
DOCUMENT_TEXT
PAGE_TEXT
OCR_TEXT
TRANSCRIPT
```

用于 inspect / locator / source reconstruction。

Retrieval Representation：

```text
RetrievalSegment
+
lexical representation
+
optional embedding
```

---

# 21. RetrievalSegment

> **RetrievalSegment = 从 File 的 searchable representation 中形成的、用于历史候选召回和 bounded inspect 的搜索单元。**

它不是业务 Domain entity，也不是新的 File。

不叫 `FileChunk`，因为它同时覆盖 PDF section、Screenshot OCR、Audio transcript、Spreadsheet region。

---

# 22. Segmentation Rule

不是所有 File 都切固定 chunk。

短内容：

```text
whole File = 1 RetrievalSegment
```

大文档优先：

```text
1. natural structure
2. page / section
3. paragraph group
4. bounded token fallback
```

fixed-size chunk 只作为 fallback；token 数和 overlap 用 Eval 决定。

---

# 23. Retrieval by File Type

PDF：section/page/window。  
DOCX：heading + paragraph group。  
XLSX：sheet + table/row region。  
Screenshot：通常 whole OCR；超长截图可拆 OCR block。  
Audio：短 transcript whole，长会议用 time-aligned windows。  
Video：V2.2 不建 semantic retrieval representation。

---

# 24. Embedding Scope

SHOULD embedding：

```text
PDF/DOCX/TXT/MD retrieval text
text-heavy screenshot OCR
audio transcript
```

MAY：textual XLSX regions。

不 embedding：

```text
raw image pixels
raw PDF bytes
raw audio bytes
video
preview image
all Messages
all Tool Results
all StateMutation
all Evidence
```

V2.2 不强制 File Summary。

---

# 25. Hybrid Retrieval

```text
User query
↓
owner / status / optional scope filter
↓
┌──────────────────────┐
│                      │
▼                      ▼
metadata/lexical    vector candidates
│                      │
└──────────┬───────────┘
           ▼
     simple rank fusion
           ▼
     aggregate by File
           ▼
   Top File Candidates
```

Lexical 留在 PostgreSQL：FTS + exact/prefix + `pg_trgm` where useful。

pgvector只负责 semantic candidate recall，不负责 truth / authority / final semantic decision。

V2.2 默认 owner-scoped exact vector search；HNSW/IVFFlat 只有 benchmark 证明需要后才启用。

Lexical + Vector 优先用 RRF/simple rank fusion，不做 cross-encoder reranker。

---

# 26. file_search

正式语义：

> **在当前用户历史 File 中找到与当前问题最相关的 File candidates，并返回少量最相关 snippet/locator。**

输入方向：

```text
query?
media_kind?
created_after?
created_before?
thing_id?
```

`query` 可以为空，只要有有意义的 filter，因此不新增 `file_list`。

输出必须聚合回 File identity：

```json
{
  "candidates": [
    {
      "file_id": "f_123",
      "filename": "软件杯通知.pdf",
      "media_kind": "DOCUMENT",
      "matches": [
        {
          "locator": {"page": 7},
          "snippet": "报名截止日期为9月19日..."
        }
      ],
      "match_reasons": ["CONTENT_LEXICAL", "CONTENT_SEMANTIC"]
    }
  ],
  "truncated": false
}
```

不把内部 vector score / ts_rank / RRF score 暴露给 Executive。

---

# 27. file_inspect

正式语义：

> **针对一个已经明确的 File，提取足够回答当前问题的 bounded、source-located 内容。**

输入：

```text
file_id
question?
locator?
```

模式：

1. 已知 locator → 精确读取；
2. 已知 File + question → 单 File 内 bounded retrieval；
3. 只有 file_id → metadata + small preview。

PDF 可返回 selected text + page；Screenshot 可返回 OCR + MAY original image；Audio 返回 transcript + timestamp。

---

# 28. Locator Preservation

Processing 必须保留 source mapping：

```text
PDF → page
DOCX → heading / paragraph
XLSX → sheet / row region
Audio → time range
Image → whole image / OCR region
```

这同时服务 `file_inspect` 与 Evidence。

---

# 29. FileProcessingGeneration

正式引入：

> **FileProcessingGeneration = 某个 File 在某个 processing/index profile 下的一套可切换派生搜索版本。**

解决 parser / OCR / embedding 升级时的无空窗 reindex。

状态：

```text
BUILDING
READY
FAILED
RETIRED
```

例如：

```text
G1 READY
G2 BUILDING
```

Search继续使用G1；G2完成后 atomic activate，再 retire G1。

Embedding失败不一定让整个 generation FAILED，只要 lexical/basic inspect 已可用。

---

# 30. RetrievalSegment 逻辑字段

```text
segment_id
file_id
generation_id
segment_order
representation_kind
content
locator
lexical/search representation
embedding?
created_at
```

最终 SQL 类型和索引 Deferred。

---

# 31. 不需要的 File/Search 表

**不需要 FileRepresentation**：Original由File/Object Storage负责；可搜索文本由RetrievalSegment负责；processing version由Generation负责。  
**不需要 FileProcessing**：Execution由DurableJob负责。  
**不需要 FileChunk**：正式概念为RetrievalSegment。  
**不需要 SearchExecution**：复用ToolExecution。  
**不需要 Generic FileReference truth**：关系语义不同，使用native relation + typed ref。

---

# 32. Search 与 Exact URL Retrieval

正式保持两个 Tool：

```text
search_web
url_inspect
```

```text
search_web
= 不知道具体页面，发现资源

url_inspect
= 已知 URL，读取指定资源
```

不能合并成万能联网 Tool。

---

# 33. Search Result

Search Result 是当前 `search_web` Action 的 Runtime Observation。

默认：

```text
ToolExecution bounded result
```

不是长期知识库，不永久保存所有结果。

Cross-run cache MAY 使用 Redis TTL，但 Cache 不承担 Evidence / Authority。

---

# 34. search_web Contract

输入方向：

```text
query
source_preference: ANY | OFFICIAL_FIRST
recency_days?
domains?
```

`OFFICIAL_FIRST` 只表示优先发现第一方/官方直接来源：

```text
OFFICIAL_FIRST
≠ OFFICIAL_ONLY
≠ automatic authority
```

Search Result 至少包含：

```text
result_ref
title
url
domain
snippet
published_at?/age?
retrieved_at
```

Provider-specific citation/search IDs 不能成为业务 identity。

---

# 35. url_inspect

正式语义：

> **对一个已知、合法 provenance 的公网 HTTP(S) URL 做 exact resource inspection。**

支持：常规 HTML / text / PDF 等；不建设 Headless Browser/CAPTCHA/登录会话平台。

`url_inspect` 失败时不能自己偷偷转 `search_web`；是否搜索由 Executive 重新决策。

---

# 36. URL Provenance Eligibility

允许 inspect 的 URL 必须来自：

```text
USER_PROVIDED_URL
SEARCH_RESULT_URL
PREVIOUS_INSPECT_REDIRECT_URL
```

不允许模型凭空构造任意 URL 触发 server-side fetch。

---

# 37. SSRF Boundary

`url_inspect` MUST：

```text
HTTP/HTTPS only
resolve DNS
reject localhost/loopback
reject private IP
reject link-local
reject cloud metadata/internal destinations
validate every redirect target
bounded redirects
cycle detection
no backend credential forwarding
```

Web内容在Model Context中始终标记为：

```text
[EXTERNAL OBSERVATION — UNTRUSTED]
```

网页中的 tool instruction / prompt / credentials request 不拥有系统授权。

---

# 38. Search Query Privacy

Search query只带完成公开检索所需的最少信息。

不得无关地把完整Memory、文件原文、手机号、私人状态等发送给Search Provider。

---

# 39. WebObservation

V2.2 不建generic `WebResource`。

> **WebObservation = 在某个时间点对某个 Web URL 的成功读取，为 durable Evidence 目的保留下来的最小 immutable observation。**

不是每次 `url_inspect` 都建。

```text
一次性回答
→ ToolExecution result即可

durable State/Memory需要来源
→ promote WebObservation
```

---

# 40. WebObservation 逻辑字段

```text
web_observation_id
owner_user_id
requested_url
final_url
title?
content_type
observed_at
retrieval_method
bounded_excerpt?
locator?
content_hash?
created_at
```

默认不保存整个HTML，不建设Internet Archive。

同一URL内容变化时创建新Observation，不覆盖旧Observation。

---

# 41. Observation → State 标准链

```text
search_web
↓
candidate
↓
url_inspect
↓
Web Observation
↓
state_get_thing_context
↓
Executive compare
↓
Policy
↓
Application mutation
↓
COMMIT
```

Search Result / WebObservation 自己永远不写 Personal State。

---

# 42. Evidence

> **Evidence = 对某个 durable fact / decision 提供支持的可定位来源引用。**

Evidence支持事实，但不自动变成事实。

---

# 43. EvidenceRef

V2.2采用typed value object：

```text
EvidenceRef
{
  source_kind
  source_id
  locator?
}
```

不是独立 Universal Evidence Entity。

Source kinds：

```text
MESSAGE
FILE
WEB
TOOL_RESULT
```

`USER_ACTION / AUTOMATION / SYSTEM` 更属于 Provenance actor/channel。

---

# 44. Provenance 与 Evidence

```text
Provenance
= 为什么这次 mutation 发生

Evidence
= 什么材料支持这个 fact
```

例如“查官网，如果变了就更新”：

```text
Provenance → User Message
Evidence   → WebObservation
```

用户直接陈述事实时，同一Message可以同时承担两种角色。

---

# 45. Typed Locator

不建设一个巨大万能 Locator JSON。

```text
MESSAGE → message/block/span
FILE    → page/section/sheet-row/timestamp/image region
WEB     → observation + heading/excerpt/page/anchor
TOOL    → tool_execution + result item/field
```

V2.2 默认只需要 primary Evidence；不建设 FactEvidence N:N 图。

不保存通用 LLM `confidence=0.83`。现实不确定性由 Domain certainty 表达。

---

# 46. User File Delete 与 Current Reality

硬规则：

> **Delete File ≠ Delete Current Reality。**

用户删除支持 Deadline 的 PDF：

```text
File → DELETED / purge
ThingDate → 保留
Memory → 默认保留
EvidenceRef → 仍指向F1，但Resolver显示DELETED
```

只有用户明确纠正 State 或 Forget Memory 时才改变相应对象。

---

# 47. User Delete 与 Orphan GC 分离

## User Delete

用户主动要求删除。即使仍被 Evidence / Memory provenance 引用，也必须允许。

## Orphan GC

系统自动清理。只有：

```text
ACTIVE
+
zero durable references
```

才有资格。

两者不能共用一个“reference_count=0才能delete”的规则。

---

# 48. User File Delete 两阶段

## Phase 1：Logical Delete

短 PostgreSQL transaction：

```text
validate owner
validate expected_version
File ACTIVE → DELETED
version++
deleted_at=now
create FILE_PURGE DurableJob
persist receipt/audit
COMMIT
```

从此：

```text
file_search不返回
file_inspect拒绝
不生成新signed URL
不生成新provider artifact
不允许新的File Evidence promotion
```

对用户已经算删除成功。

## Phase 2：Physical Purge

Durable Worker幂等清理：

```text
raw object bytes
preview derivatives
parsed text
OCR
transcript
RetrievalSegments
embeddings
provider artifacts
file-derived internal caches
file-derived Tool Result content copies
```

完成后设置 `purged_at`。

---

# 49. File Tombstone

不直接 hard-delete File row。

保留 privacy-minimal tombstone：

```text
file_id
owner_user_id
asset_status=DELETED
deleted_at
purged_at
```

用于未来解释“这个Evidence来源曾经存在但被用户删除”。

Tombstone禁止保留raw bytes、parsed text、OCR、transcript、segments、embeddings、preview、verbatim source copy。

---

# 50. File-derived Tool Result Redaction

`file_search / file_inspect` 的 ToolExecution 可能持久化 source snippet。

File Delete 后：

```text
ToolExecution identity/status
→ 保留

source-derived content payload
→ redact/scrub
```

避免“原文件删了，但Runtime receipt还永久保留原文”。

历史Assistant Message默认不自动改写；删除Conversation走Delete Thread生命周期。

---

# 51. File Delete 后 Memory

默认Memory保留，provenance解析为File DELETED。

如果用户明确：

> “把从这份文件记住的东西也忘掉。”

则执行独立 Memory Forget，而不是File Delete级联。

---

# 52. Orphan File

正式定义：

> **Orphan File = `ACTIVE`，用户未主动删除，但已经没有任何 durable business reference 指向它。**

Durable references可能包括：

```text
MessageAttachment
Thing/File业务关联
EvidenceRef
StateMutation provenance
Memory provenance
Automation context
其他持久化业务引用
```

---

# 53. Orphan Detection

不使用实时 `durable_reference_count`，也不建设 generic `file_references` truth。

采用：

```text
真实structural relation → native FK/join
Evidence/Provenance → typed ref
Orphan → background scanner聚合检查
```

流程：

```text
ACTIVE Files older than grace
↓
check all durable references
↓
zero refs
↓
orphan candidate
↓
delete-time recheck
↓
purge
```

具体grace period Deferred。

---

# 54. Temporary Upload GC

Object Storage已经写入但File DB transaction没成功：

```text
object exists
File不存在
```

这是Temporary Upload Garbage，不是Orphan File。

通过pending prefix lifecycle / multipart abort / periodic GC清理。

---

# 55. 四种 Delete/Retention 语义

| 类型 | 触发者 | 需要zero refs | 立即不可访问 | 最终清内容 |
|---|---|---:|---:|---:|
| User Delete | 用户 | 否 | 是 | 是 |
| Account Delete | 用户 | 否 | 是 | 是，全账户 |
| Orphan GC | 系统 | 是 | GC时 | 是 |
| Temporary Upload GC | 系统 | 不适用 | 从未正式可用 | 是 |

---

# 56. Evidence Source Status

EvidenceRef不保存可变source_status。

读取时由EvidenceResolver动态解析：

```text
AVAILABLE
DELETED
UNAVAILABLE
MISSING
```

`DELETED`表示稳定identity仍存在但内容已按用户要求清理；`UNAVAILABLE`表示逻辑存在但暂时无法访问；`MISSING`通常是integrity/migration bug。

动态Resolver避免File删除后批量改写所有EvidenceRef。

---

# 57. WebObservation Retention

有durable reference → retain。  
无durable reference → eligible for background GC。

Web live URL后来404，不会改变历史WebObservation，也不会自动改变Current State。

---

# 58. Delete-vs-Inspect Race

```text
T1 Agent file_inspect(F1)
T2 User Delete F1
T3 Agent准备写ThingDate
```

任何基于File的durable Evidence Promotion / State Mutation，在Application COMMIT前 MUST 重新验证：

```text
F1.asset_status == ACTIVE
```

否则拒绝新的durable fact。

已经发给模型的Request无法物理撤回，但Delete后不再发起新读取、不允许新Evidence promotion、不允许新File-based State mutation。

---

# 59. Signed URL

下载/预览 MAY 使用short-lived signed URL。

```text
signed URL
≠ File identity
```

Logical Delete 后不再签发新URL，并尽快物理删除object。具体TTL Deferred。

如果未来要求绝对即时吊销，可升级为authenticated backend proxy download。

---

# 60. Account Delete

Account Delete必须先做Deletion Fence，防止“边删边生成”。

进入删除流程后阻止：

```text
new Run
new Upload
new Memory formation
new Automation
new File processing generation
new durable business write
```

Worker finalize前必须验证account/File/generation仍允许提交；已进入deletion则discard result。

---

# 61. Account Purge

使用PostgreSQL durable `ACCOUNT_PURGE` job：

```text
fence user
↓
stop future work
↓
purge Files raw bytes
↓
purge RetrievalSegments/embeddings
↓
purge provider artifacts
↓
purge Search runtime/cache
↓
purge WebObservations/Evidence payloads
↓
purge Messages/Threads
↓
purge Personal State
↓
purge Memory
↓
purge Automation/Device/Push data
↓
delete/anonymize minimal metadata per policy
```

具体法务/安全日志retention由独立合规策略决定。

---

# 62. pgvector Delete

Embedding与RetrievalSegment同PostgreSQL，因此删除segment row即删除对应vector data。

不需要VectorCleanupService或独立向量库对账。

---

# 63. Security Boundary

File Upload最低要求：

```text
authenticated owner
extension/type allowlist
validated MIME
file signature/magic check
size limit
page/dimension/duration/resource limits
application-generated storage key
private Object Storage
no direct execution
parser isolation
timeout/memory limit
no unnecessary parser network
short-lived authorized download
```

不信客户端Content-Type，不把用户原始文件名直接作为storage key。

V2.2不建设企业级Malware Platform，但未来可追加`FILE_SECURITY_SCAN` DurableJob。

URL侧继续遵守SSRF/private-network/redirect安全边界。

---

# 64. Final Logical Data Model

最终新增/确认核心对象：

```text
File
MessageAttachment
FileProcessingGeneration
RetrievalSegment
WebObservation
```

已有对象：

```text
DurableJob
ToolExecution
Message
Personal State entities
StateMutation
Memory
Automation
```

Value Objects：

```text
EvidenceRef
ProvenanceRef
Typed SourceLocator
```

---

# 65. 为什么每个对象存在

## File
解决stable internal identity、owner、raw asset lifecycle、storage mapping、logical delete/tombstone。**必须有。**

## MessageAttachment
表达Message→File结构关联。若现有关系已存在则复用。

## FileProcessingGeneration
解决parser/embedding升级时无空窗reindex。**需要。**

## RetrievalSegment
解决historical lexical/vector search、OCR/transcript search、large PDF bounded inspect、locator。**需要。**

## WebObservation
解决“同一URL会变，但长期Evidence需要知道当时看到了什么”。**selective需要。**

---

# 66. 明确不建的逻辑表

```text
FileRepresentation      → 不需要
FileProcessing          → 复用DurableJob
FileChunk               → 使用RetrievalSegment
SearchExecution         → 复用ToolExecution
Universal Evidence      → 使用EvidenceRef Value Object
FactEvidence N:N        → Deferred
Generic FileReference   → 不作为truth
Universal Source        → 禁止
```

---

# 67. 逻辑关系图

```text
┌──────────────────────────┐
│           File           │
│ stable raw asset         │
└────────────┬─────────────┘
             │ 1:N
             ▼
┌──────────────────────────┐
│ FileProcessingGeneration │
│ parser/index generation  │
└────────────┬─────────────┘
             │ 1:N
             ▼
┌──────────────────────────┐
│    RetrievalSegment      │
│ text + locator + vector  │
└──────────────────────────┘

Message
  │
  └── MessageAttachment ───→ File

Thing / State / Memory / Mutation
  │
  └── EvidenceRef / ProvenanceRef
         │
         ├── MESSAGE → Message
         ├── FILE ───→ File
         ├── WEB ────→ WebObservation
         └── TOOL ───→ ToolExecution

DurableJob
= processing / reindex / purge / account purge

ToolExecution
= file_search / file_inspect / search_web / url_inspect execution
```

---

# 68. Authority Matrix

| 对象 | 角色 |
|---|---|
| File | durable raw asset |
| raw bytes | durable asset content |
| FileProcessingGeneration | derived infrastructure state |
| RetrievalSegment | derived searchable representation |
| embedding | derived semantic index |
| Search Result | runtime observation |
| WebObservation | durable external observation |
| EvidenceRef | supporting source reference |
| Memory | durable long-term knowledge |
| Personal State | **current reality authority** |

---

# 69. Final Agent-facing Tool Boundary

最终仍只有：

```text
file_search
file_inspect
search_web
url_inspect
```

不增加：

```text
file_list
file_get_metadata
file_ocr
file_embed
file_reindex
web_save
evidence_create
```

这些是Application/Infrastructure内部能力，不是Executive需要独立选择的业务动作。

---

# 70. User Journey 验证

## 当前截图

Upload → File → MessageAttachment → Current Attachment → native vision → answer。只有用户明确要求保存现实，才调用State mutation并附EvidenceRef。

## 当前20页PDF

Provider支持且budget允许时raw PDF direct；后台独立生成text/page map。当前回答不先走RAG。

## 三个月后的PDF

`file_search("软件杯 报名截止") → F1/P7 snippet → file_inspect(F1, question) → bounded answer`。

## 历史截图

OCR segment让`file_search`能找到截图；`file_inspect`可返回OCR + MAY original image。

## 指定URL

用户URL → `url_inspect`；不是`search_web`。

## Web Search

`search_web(OFFICIAL_FIRST) → candidates → url_inspect chosen source → answer`。不自动写State。

## Search后更新State

Search → Inspect → Evidence → Read Current State → Executive Compare → Policy → State Mutation。

## 删除原文件

File→DELETED/purge；EvidenceRef→DELETED source；ThingDate与Memory默认保留。

## Parser crash

File仍ACTIVE；Provider支持raw PDF时当前回答仍可进行；后台retry。

## Provider artifact过期

Object Storage raw bytes仍在；Adapter重新upload；internal file_id不变。

---

# 71. Failure Matrix

| Failure | V2.2收敛 |
|---|---|
| Object upload成功、DB File commit失败 | pending object GC |
| DB File存在但object缺失 | integrity failure，不伪装可读 |
| multipart未完成 | storage lifecycle/abort |
| parser crash | File仍ACTIVE，retry |
| OCR crash | current image仍可用，historical text recall降级 |
| embedding crash | lexical继续，semantic降级 |
| provider upload timeout | internal File不受影响 |
| provider artifact expired | re-upload from Object Storage |
| duplicate upload | 两个File均可存在，hash仅hint |
| oversized file | File commit前reject |
| fake MIME | Backend sniff/signature reject |
| malicious PDF | isolated parser/resource limit |
| URL localhost/private | SSRF deny |
| redirect private IP | each-hop validation |
| redirect loop | bounded + cycle detect |
| URL content changed | new WebObservation |
| Search timeout | READ_ONLY bounded retry |
| bad Search Result | candidate only，不直接写State |
| Evidence File deleted | State保持，Resolver=DELETED |
| live URL 404 | old WebObservation仍能解释历史 |
| File delete during inspect | commit前source lifecycle revalidation |
| Account Delete during processing | deletion fence + discard late result |
| Redis down | PostgreSQL truth + polling |
| Worker crash | lease expiry + Recovery Scanner |
| duplicate processing job | generation/profile unique semantics |
| old embedding version | old active generation继续服务 |
| stale Search cache | cache无authority；fresh inspect用于mutation |
| physical purge object delete失败 | logical delete已生效；durable retry |
| purge Worker crash | idempotent resume |
| signed URL已发 | stop new URL + short TTL + object delete |
| ToolResult还留File原文 | redact source-derived payload |

---

# 72. V1 → V2.2 Migration Boundary

当前架构资料不足以冻结真实V1字段级Schema，因此本文只冻结Migration Strategy，不编造SQL。

最终SQL Migration必须读取当前Repository/DB Schema后设计。

---

# 73. Migration Strategy

采用：

```text
EXPAND
↓
BACKFILL
↓
DUAL COMPATIBILITY
↓
SWITCH
↓
VERIFY
↓
CONTRACT
```

不做big-bang migration。

### Phase 1 — Expand

增加stable File identity/lifecycle、Generation、RetrievalSegment、WebObservation、EvidenceRef-compatible contract。

### Phase 2 — Backfill File

旧附件映射为V2 File；旧ID若是稳定internal ID可保留，若是provider/path则创建新file_id。

### Phase 3 — Backfill MessageAttachment

旧Message→provider/path迁为MessageAttachment→internal File。

### Phase 4 — Background Retrieval Build

对已有File异步建立generation/segments/lexical/embedding，不要求上线前一次性全部重建。

### Phase 5 — Switch Retrieval

达到质量目标后`file_search/file_inspect`切到V2 retrieval。

### Phase 6 — Evidence Migration

旧source映射MESSAGE/FILE/WEB/TOOL；历史没有来源时保持unknown/legacy absent，禁止编造Evidence。

### Phase 7 — Stop Legacy Writes

新写只走V2，legacy仅兼容读。

### Phase 8 — Contract Old Index

确认mapping完整、retrieval Eval通过、无代码使用old chunk/source IDs、rollback窗口结束后才清理旧结构。

---

# 74. 官方设计依据

本文使用官方资料校准设计，但不机械照搬Provider实现。

## OpenAI

Responses API支持text/image/file input和built-in web/file search：  
https://developers.openai.com/api/reference/responses

用于验证Current Attachment可以直接作为Model Input，同时Provider Search/File ID不应成为内部业务identity。

## Anthropic

Files API：  
https://platform.claude.com/docs/en/build-with-claude/files

Web Search：  
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool

Web Fetch：  
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool

Tool Combinations：  
https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-combinations

用于验证“Search discovery → Fetch exact URL”的两阶段Web模式，以及Provider File artifact与业务identity分离。

## Google Gemini

File Input Methods：  
https://ai.google.dev/gemini-api/docs/file-input-methods

Files API：  
https://ai.google.dev/gemini-api/docs/files

Google Search Grounding：  
https://ai.google.dev/gemini-api/docs/google-search

URL Context：  
https://ai.google.dev/gemini-api/docs/url-context

用于验证inline/current file、Files API、Google Search、URL Context是不同能力层；Provider artifact具有自己的生命周期。

## PostgreSQL

Full Text Search：  
https://www.postgresql.org/docs/current/textsearch.html

Text Search Controls：  
https://www.postgresql.org/docs/current/textsearch-controls.html

pg_trgm：  
https://www.postgresql.org/docs/current/pgtrgm.html

用于验证lexical search可以继续留在PostgreSQL，不需Elasticsearch。

## pgvector

https://github.com/pgvector/pgvector

用于验证exact/approximate vector search，以及PostgreSQL FTS + pgvector hybrid search / RRF方向。

## OWASP

File Upload Cheat Sheet：  
https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html

SSRF Prevention：  
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

用于冻结allowlist、MIME/signature validation、private storage、parser isolation、SSRF/private-network/redirect安全边界。

---

# 75. Frozen Decisions

1. File是实际持有raw bytes的稳定私有资产。
2. File使用internal stable `file_id`。
3. Provider file ID/URI/signed URL/storage URL不做业务identity。
4. File raw bytes immutable，新版本创建新File。
5. File lifecycle仅`ACTIVE/DELETED`。
6. PostgreSQL管metadata/lifecycle，Object Storage管bytes。
7. File commit point是object verify + DB commit。
8. pending upload与正式File分离。
9. Current Attachment与Historical Retrieval两条路径。
10. Current Attachment capability/budget/security允许时direct-to-model。
11. Current Attachment不默认等待OCR/chunk/embedding/summary。
12. ModelContextAssembler保持Provider-neutral。
13. ProviderArtifact只是可重建cache。
14. File Processing复用DurableJob，Redis只wake-up。
15. Processing failure不等于File unusable。
16. Screenshot当前native vision，历史OCR searchable。
17. PDF当前native document优先，历史text+locator。
18. DOCX必须有自己的basic extraction fallback。
19. Voice Input默认STT→Message，不默认建File。
20. Audio File transcript是provider-neutral baseline。
21. Video File V2.2只保证upload/storage，semantic Deferred。
22. Historical File正式`file_search→file_inspect`。
23. 不做Universal Chunking。
24. RetrievalSegment是统一历史搜索单元。
25. Segmentation优先结构/page/paragraph，fixed-size只fallback。
26. Embedding只用于有历史语义价值的text segment。
27. 普通照片不默认Caption/visual embedding。
28. 不强制File Summary。
29. Historical Search使用PostgreSQL lexical + pgvector hybrid。
30. pgvector只做semantic candidate recall。
31. exact vector search first，HNSW/IVFFlat benchmark后再开。
32. Lexical+Vector优先RRF/simple fusion。
33. `file_search`输出File candidate + snippet + locator。
34. `file_inspect`输出bounded source-located context。
35. Processing必须保留source locator。
36. 需要FileProcessingGeneration。
37. 需要RetrievalSegment真实持久化。
38. 不建设generic FileRepresentation表。
39. 不建设FileProcessing执行表。
40. 不建设SearchExecution。
41. Search与Exact URL分别为`search_web/url_inspect`。
42. URL不是File。
43. Search Result默认是ToolExecution runtime result。
44. Cross-run Search Cache只能是TTL优化，不是authority。
45. Official-first只是discovery preference。
46. durable Web source用immutable WebObservation。
47. WebObservation selective promotion，不是每次fetch都永久保存。
48. WebObservation不默认保存整个网页。
49. `url_inspect`只访问合法公网HTTP(S)。
50. URL必须有用户/Search provenance，模型不能任意构造server fetch目标。
51. URL读取必须防SSRF和redirect绕过。
52. Web内容始终untrusted。
53. Search Tool永远不直接写Personal State。
54. Web-based State mutation走Search→Inspect→Evidence→Read State→Compare→Policy→Mutation。
55. EvidenceRef是typed value object，不是Universal Evidence表。
56. Evidence source kinds为MESSAGE/FILE/WEB/TOOL_RESULT。
57. Provenance与Evidence分离。
58. Locator按source kind typed。
59. V2.2默认只需primary Evidence，不建FactEvidence图。
60. 不保存通用LLM confidence。
61. Delete File不自动修改Current State。
62. User File Delete=立即logical delete + async physical purge。
63. User Delete不要求zero refs。
64. File Delete必须清raw/parsed/OCR/transcript/segments/embeddings/provider artifacts/internal copies。
65. File tombstone只保留最小删除解释。
66. File-derived Tool Result payload允许/必须redact。
67. Delete File默认不重写历史Conversation output。
68. Delete File默认不Forget Memory。
69. Orphan=ACTIVE+zero durable references。
70. Orphan GC与User Delete严格分离。
71. 不维护实时reference_count。
72. 不建设generic file_references truth。
73. Orphan采用真实关系检查+background scanner+grace+recheck。
74. Evidence source status由Resolver动态解析。
75. WebObservation无durable reference即可GC。
76. File-based durable mutation commit前重新验证source ACTIVE。
77. signed URL只作短期授权，不作identity。
78. Account Delete先fence新写入，再durable purge。
79. Account Delete期间Worker finalize必须检查account/File/generation有效。
80. pgvector随RetrievalSegment row删除，不建独立vector cleanup。
81. File Upload必须有allowlist、MIME/signature validation、resource limit、private storage、parser isolation。
82. V2.2不建设企业级Malware Platform。
83. Agent-facing材料Tool最终仅`file_search/file_inspect/search_web/url_inspect`。
84. V1→V2.2采用Expand→Backfill→Switch→Contract。
85. Migration不得为历史数据编造Evidence/Provenance。
86. 字段级SQL Migration必须基于真实Repo/Schema后再冻结。
87. 各Domain保持identity/lifecycle，只共享轻量Retrieval/Evidence思想，不引入Universal Source。

---

# 76. Deferred Details

## File / Storage

- 最终 SQL 字段类型；
- Storage Provider；
- upload session contract；
- multipart strategy；
- signed URL TTL；
- upload size/page/duration limits；
- pending upload retention；
- purge retry/backoff。

## Processing

- Parser library；
- OCR engine；
- transcription provider；
- processing profile版本表示；
- active generation切换实现；
- parser isolation实现。

## Retrieval

- segment大小和overlap；
- PDF structure parser；
- XLSX region策略；
- tsvector config；
- 中文 lexical具体方案；
- embedding model/dimension；
- Top-K；
- RRF参数；
- exact→HNSW阈值。

## Evidence / Web

- EvidenceRef最终typed/JSON表达；
- Locator最终schema；
- State各实体primary_evidence字段位置；
- Memory provenance具体存储；
- WebObservation excerpt长度；
- Search Provider Adapter；
- URL fetch timeout/redirect max；
- cache TTL。

## Delete / Migration

- orphan grace；
- physical purge SLA；
- tombstone retention；
- Account deletion exact state machine；
- 当前V1真实schema与exact SQL migration。

---

# 77. Backend Freeze 验收问题

1. **File是什么？** 真实持有raw bytes的稳定私有资产。  
2. **当前附件为什么不默认RAG？** 它本身就是当前输入，direct multimodal更快、更完整。  
3. **历史为什么search→inspect？** 先少量候选召回，再针对明确File精读。  
4. **File/Memory/State/Evidence区别？** 原始资料/长期知识/当前现实/事实支持引用。  
5. **图片、PDF、语音怎么进Agent？** Vision/native document/STT或transcript。  
6. **什么做embedding？** 有历史语义检索价值的text RetrievalSegment。  
7. **pgvector干什么？** semantic candidate recall。  
8. **Search和URL为什么不同？** discovery vs exact resource inspection。  
9. **Search为什么不能改现实？** Observation没有State authority。  
10. **Evidence为什么不需要KG？** 大部分事实只需一个typed primary source ref。  
11. **Delete File为什么不Delete State？** 删除材料不等于撤销现实。  
12. **Evidence来源删后怎么办？** stable ref保留，Resolver显示DELETED/UNAVAILABLE。  
13. **什么File是orphan？** ACTIVE且没有任何durable business reference。  
14. **Provider artifact丢失怎么办？** 从internal File/Object Storage重新上传。  
15. **半年后能找材料吗？** 文档/截图/音频文本通过hybrid file_search→inspect。  
16. **Account Delete能真清吗？** deletion fence + durable purge覆盖raw/derived/vector/cache/ref。  
17. **怎么避免变重型RAG？** Current direct、Selective Processing/Embedding、No Universal Source、No mandatory Summary。  
18. **怎么保持个人Agent定位？** 只有4个材料Tool，能力围绕对话/事项/现实维护，而非文档管理SaaS。

---

# 78. 一句话定义

> **老实人 File / Multimodal / Search / Evidence v2.2 是一套以稳定 File 资产和当前附件直接多模态理解为起点、以 PostgreSQL RetrievalSegment + lexical/pgvector hybrid 负责历史材料候选召回、以 `search_web / url_inspect` 区分外部资源发现与精读、以轻量 typed EvidenceRef 连接 Observation 与 durable fact、并通过逻辑删除、durable physical purge、orphan scanner 和 account deletion fence 保证数据生命周期真实可控的个人 Agent 资料基础设施；它明确拒绝把 File、Memory、State、Evidence 和 Search Result 合并成一个万能 RAG/Knowledge Base。**
