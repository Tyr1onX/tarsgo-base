# TARS-Go Platform

TARS-Go 是一个面向高校机器人战队的开源协作平台。

当前产品方向是一个**公开的运营协作看板**，用于宣传、活动执行、招新、物资、直播、摄影等工作。

讨论仍然可以发生在微信、会议或线下。TARS-Go 负责记录已经明确下来的工作，并让团队持续看到当前执行状态。

机械、电控、算法等技术研发工作流不属于当前 V0.2 的范围。

## 当前工作流

~~~text
admin 可选择将自然语言需求转换为可编辑的 AI 草稿
-> 人工编辑 / 删除 / 新增草稿分工
-> 确认后以原子事务创建一个运营事项及其一级分工
-> admin / manager 也可以手动发布运营事项
-> 一个事项可以随执行过程逐步拆成一层执行任务
-> 负责人可以直接指定，也可以开放认领
-> 协作者可以直接指定，也可以在开放协作时自行加入
-> 所有 active 成员都能看到已发布工作
-> 负责人 / 协作者发布进展；负责人完成自己的分工
-> admin / manager 持续让事项结构和人员分配与现实保持一致
~~~

相关文档：

- docs/operations-workflow.md — 产品工作流与任务颗粒度规则
- docs/ai-direction.md — AI 的长期定位与明确边界

## 技术栈

- Vue 3 + TypeScript + Vite
- FastAPI
- SQLAlchemy + PyMySQL
- Alembic
- MySQL 8.4 LTS
- Caddy
- Docker Compose

## 权限

系统角色与现实中的战队职务相互独立。

### admin

- 管理成员账号
- 创建、编辑和重新分配全部运营事项与执行任务
- 使用 active 成员可用的同一套认领 / 协作操作

### manager

- 创建、编辑和重新分配全部运营事项与执行任务
- 读取分配任务所需的最小 active 成员列表
- 无成员账号管理权限

### member

- 查看全部已发布的运营工作
- 查看自己负责或参与协作的工作
- 查看当前可认领的工作
- 在开放负责人认领时认领无负责人的任务
- 当任务未完成且仍允许认领时取消自己的认领
- 加入 / 退出开放协作
- 为自己负责或协作的子任务发布进展
- 完成自己负责的子任务并记录执行结果
- 根据自己发布的进展，请求 AI 提取已确认事实的建议

后端鉴权是安全边界。

## 任务模型

V0.2 继续使用现有 tasks 表，不新增 Activity 模型。

一个任务可以是：

- 根事项（parent_id = NULL），表示一个运营事项
- 一级子任务（parent_id = 根任务 id），表示一个执行分工

当前任务字段包括：

- title
- 可选的子任务结果检查项（“做到什么算完成”；根事项不重复设置总完成标准）
- 执行要点（最多 6 条短文本）
- 注意事项（最多 5 条短文本）
- 前置条件（最多 4 条短文本；用于可读说明，与结构化依赖分离）
- 同一事项下的子任务依赖（manager 可编辑；blocked 根据未完成依赖计算）
- 可选负责人
- owner_claimable
- collaborators
- collaboration_open
- parent id
- 可选截止时间（仅在有明确时间约束时设置）
- 状态：todo | doing | done

已发布任务必须满足：已有负责人，或允许负责人认领。

V0.2 只支持一层子任务。禁止创建孙级任务。

认领后状态仍保持 todo。首次发布进展时，todo 子任务变为 doing；后续进展不会再次改变状态。完成子任务时，会在一个事务中保存实际结果、标记为 done，并创建关联的 ItemActivity。用户可以选择在同一事务中将完成结果同步到根事项的当前信息。根事项状态由子任务推导：全部 todo 则为 todo；只要已有任务开始但未全部完成则为 doing；全部完成则为 done。没有子任务的事项保留自身原有状态。

依赖关系只允许连接同一根事项下的一级任务。只要任一依赖未完成，任务即为 blocked，此时进展和完成接口均不可用。依赖不能指向任务自身、不能跨事项，也不能形成环。`blocked` 是计算字段，不是第四种任务状态。

历史任务可以继续引用 disabled 成员。无关编辑不会重新校验已有分配；新提交的负责人和协作者必须是 active。

## 页面

- /login — 邮箱 / 密码登录
- /invite/:token — 一次性密码设置
- / — “我现在需要做什么？”首页
- /tasks — 所有角色统一的任务入口
- /ai-planner — 仅 active admin 可访问的 AI 规划工作区；不进入全局导航
- /knowledge — 仅 admin 可访问的 GitHub 与文档知识管理；在桌面端主导航中可见
- /team — 仅 admin 可访问的成员账号管理
- /me — 个人信息、系统角色与退出登录

/tasks 向所有 active 成员提供三个视图：

- **我的** — 自己负责或参与协作的任务
- **待认领** — 无负责人、未完成且开放公开认领的任务
- **全部** — 全部已发布的运营事项与执行任务

admin / manager 可以在同一任务页面打开轻量表单，创建根事项或在事项下新增一个执行任务。

旧路径 /admin/tasks 会重定向到 /tasks，/admin/members 会重定向到 /team。

## 认领与协作

负责人认领在数据库更新边界上是原子的：当一名成员已经认领无负责人的任务后，第二名认领者会收到冲突，而不会覆盖现有负责人。

成员只有在以下条件同时满足时才能取消自己的认领：

- 自己是当前负责人
- 任务尚未完成
- 任务仍标记为可认领

开放协作允许 active 的非负责人在任务未完成时自行加入或退出协作。

admin / manager 始终可以通过正常的任务编辑重新分配负责人和协作者。

## 认证与成员生命周期

密码通过 pwdlib 使用 Argon2 哈希。

登录使用不透明的随机 HttpOnly Cookie：

- 只有 Cookie 中保存原始 session token
- MySQL 只保存 SHA-256 token 哈希
- SameSite 为 Lax
- 生产环境 HTTPS 必须设置 SESSION_COOKIE_SECURE=true
- session 七天后过期
- 停用账号会立即删除其全部 session

邀请 token 同样是不透明随机值，数据库只保存其哈希。邀请七天后过期，并在激活后删除。

成员状态为 invited、active 和 disabled。

只有 active 账号可以使用任务认领或协作 API，因为每个操作都要求有效的 active session。

## 共享执行场景

`/tasks/:id` 为子任务负责人或协作者提供主要的“更新进展”操作。发布进展会创建一个关联到该子任务的 ItemActivity，并且只会将 todo 推进为 doing；如果任务已经是 doing，则进展不会改变其状态。完成任务会在一个事务中保存实际结果、标记为 done，并创建关联 activity；只有负责人或 manager 可以完成任务。完成时还可以选择在同一事务中把结果加入根事项的当前信息。

根事项状态由子任务确定性推导：全部 todo → todo；至少一个已开始但尚未全部完成 → doing；全部完成 → done。没有子任务的根事项保留自身原有状态。UI 会汇总已完成、进行中、未开始和 blocked 工作，但不会把 blocked 当作状态。

manager 可以将同一事项下的子任务关联为前置依赖。系统拒绝循环依赖、自依赖和跨事项依赖。只要任一关联前置任务未完成，子任务即为 blocked。现有的自然语言前置条件仍作为说明文本保留。

进展保存后，前端可以发起一次 AI 请求，从中提取最多五条已经确认的事实。后端会发送有边界的任务 / 事项上下文，并脱敏成员姓名和邮箱地址。建议在人工选择前只保存在本地；批量接口会去除完全重复项，并强制执行 30 条事实的上限。AI 失败不会回滚已经保存的进展。具有进展发布权限的成员可以使用该提取接口，并计入现有共享的每日 AI 配额。

任务详情页会在浏览器重新获得焦点或重新可见时刷新，并且仅在任务详情打开期间每 60 秒轮询一次。后台刷新会保留尚未保存的结果文本。

普通成员的一级分工状态与结果只能通过进展 / 完成接口修改，不能通过通用 PATCH 绕过前置依赖、完成结果与动态记录。没有子任务的独立根事项保留原有状态更新能力。管理者修改负责人、截止时间或纠正状态时会同时生成简短事项动态；实际未变化的字段不重复记录。

执行相关 API 新增 `POST /api/tasks/{task_id}/progress`、`POST /api/tasks/{task_id}/complete`、`POST /api/tasks/{root_task_id}/context-facts/batch` 和 `POST /api/ai/items/{root_task_id}/extract-facts`。`TaskOut` 包含 `depends_on_tasks`、计算字段 `blocked` 与 `blocked_by`；manager 在创建 / 更新任务时通过 `depends_on_task_ids` 设置依赖。

## AI Planner

V0.2 第二阶段的第一小步实现了一个轻量规划流程：

~~~text
自然语言需求
-> 一份结构化 AI 草稿
-> 人工编辑 / 删除 / 新增草稿分工
-> 后端确定性校验
-> 明确确认
-> 在一个事务中创建一个根事项 + 一级分工
~~~

Planner 不是聊天机器人，并且在生成阶段绝不会写入任务。它不能返回成员 ID，也不能分配真实成员。

进展事实提取独立于 Planner Generate / Refine / Execution Review：只有有权发布原始进展的 active 成员可以使用；每次显式提取只发起一次模型请求；最终仍需人工应用建议。

访问需要同时满足：

- 已认证的 active 用户
- 系统角色为 admin
- AI_PLANNER_ENABLED=true
- 按 AI_PROVIDER 配置对应的服务端 API key 和模型名（Gemini 使用 GEMINI_API_KEY、GEMINI_MODEL）

前端只有在 /api/ai/planner/access 表示可用时才显示入口。Planner POST 接口还会再次执行权威校验。

Planner 先使用自然语言输入，再生成可编辑的结构化草稿。每个分工包含完成标准、简洁执行要点、注意事项与前置条件。前置条件仅用于可读说明，并不是数据库依赖。admin 可以通过单卡片或整份草稿的自然语言 Refine 修改内容；每个操作都只发起一次 SDK 模型请求，并且局部修改只合并到目标卡片。支持不超过 10 MiB 的 `.md`、`.txt`、`.docx` 和 `.pdf` 文件；文件只做临时提取，不写入 Knowledge，也不使用 OCR。Planner 会在后台自动搜索一组有边界的本地 Knowledge Source 文档，并且不会在 Planner UI 中展示来源列表或检索控件。没有 agent loop、自动反思、数据库任务全量导出或向量检索。输入描述最多 5000 字符，当前活动材料最多 5000 字符，知识上下文最多 8000 字符，输出最多 15 个分工 / 6 个问题。官方 OpenAI Python SDK 被配置为禁用自动重试。系统为每位成员持久化 UTC 日维度计数，默认将 Generate、Refine 和 Review 合计限制为每天 100 次请求；可通过 `AI_PLANNER_DAILY_REQUEST_LIMIT` 修改这一共享上限。系统只保存聚合的输入 / 输出 / 总 token 用量及知识上下文字数，不保存 prompt 或草稿文本。

### AI Planner 配置

生产环境 .env 新增：

~~~text
AI_PLANNER_ENABLED=true
AI_PLANNER_DAILY_REQUEST_LIMIT=100
AI_PROVIDER=gemini
AI_BASE_URL=
GEMINI_API_KEY=<server-side key from Google AI Studio>
GEMINI_MODEL=gemini-3.8-flash

# OpenAI:
# AI_PROVIDER=openai
# AI_API_KEY=<server-side key>
# AI_MODEL=<structured-output-capable model>

# DeepSeek:
# AI_PROVIDER=deepseek
# AI_BASE_URL=https://api.deepseek.com
# AI_API_KEY=<server-side key>
# AI_MODEL=deepseek-flash
~~~

仓库中只包含空值 / 禁用状态的占位配置。API key 永远不会发送到前端，也不会通过 API 响应返回。

Gemini 使用 Google 官方 `google-genai` Python SDK 的 Interactions API，通过 `response_format` 发送 `AIPlannerDraft` 的 JSON Schema，并在服务端再次用 Pydantic 校验输出。请求设置 `store=false`，SDK 重试次数设为 1（仅首次调用），不保存完整 prompt 或草稿。默认示例模型 `gemini-3.8-flash` 当前包含在 Gemini Developer API Free Tier；免费额度和条款由 Google 管理，Free Tier 请求可能用于改进 Google 产品，敏感资料应按团队的数据处理要求选择服务层级。

OpenAI 和 DeepSeek 适配器继续使用官方 OpenAI Python SDK。OpenAI 继续使用 responses.parse(..., text_format=AIPlannerDraft)。DeepSeek 连接其官方的 OpenAI-compatible Responses API（https://api.deepseek.com），但只调用一次 responses.create，并使用 text.format.type=json_schema、strict=true 和 AIPlannerDraft.model_json_schema()，随后通过 json.loads() 与 AIPlannerDraft.model_validate() 在本地校验 response.output_text。不存在 parse 后再 create 的 fallback，因此一次 Generate 操作仍然只执行一次模型请求。

### 配置 Gemini API Key

1. 登录 [Google AI Studio 的 API Keys 页面](https://aistudio.google.com/app/api-keys)，选择项目并创建 API Key。
2. 将密钥直接写入部署服务器的 `.env`，例如 `GEMINI_API_KEY=...`。不要放进前端环境变量、仓库文件、聊天或日志。
3. 在 `.env` 中设置 `AI_PROVIDER=gemini`、`GEMINI_MODEL=gemini-3.8-flash` 和 `AI_PLANNER_ENABLED=true`，然后按常规方式重建并启动服务。

Gemini 密钥仅通过 Compose 传给 API 容器。Planner 继续使用当前 `/api/ai/planner` 接口、管理员权限、现有额度和 `/api/tasks/batch` 确认创建流程。

## 数据库迁移

当前 Alembic 链：

~~~text
0001_v0_1
-> 0002_operations_claiming
-> 0003_ai_planner_usage
-> 0004_knowledge_documents
-> 0005_task_execution_details
-> 0006_dynamic_item_execution
-> 0007_shared_execution_scene
-> 0008_scoped_item_information
-> 0009_optional_task_deadlines
~~~

它会在不删除数据的前提下升级现有 V0.1 tasks 表：

- 保留现有 owner_id
- owner_id 改为可空
- 新增可空 parent_id
- owner_claimable 默认 false
- collaboration_open 默认 false
- 现有完成标准和状态保持不变

CI 使用预置的旧版数据，包含真实的 0001_v0_1 -> 0002_operations_claiming 兼容性检查。

迁移会为执行要点、注意事项和前置条件新增 JSON 数组，并为现有任务回填空数组。`0007_shared_execution_scene` 为 `item_activities.task_id` 新增可空字段（旧 activity 记录保持未关联），并新增同一事项内的 `task_dependencies` 关联表。`0008_scoped_item_information` 将旧版根事项 `context_facts` 迁移为全局 `ItemFact` 记录，然后移除该 JSON 列；相关事实会关联到同一事项的子任务。
`0009_optional_task_deadlines` 只将 `tasks.deadline` 改为可空，保留所有已有截止时间；事项与分工独立保存日期，无可靠时间约束时使用 `null`，分工不会继承事项截止时间。

## Knowledge Source V0.1

admin 可以在 `/knowledge` 中，仅同步一个已配置 GitHub 仓库下的指定路径，或单独上传 `.md`、`.txt`、`.docx` 和 `.pdf` 文件。GitHub 访问只读；凭据保存在服务端 `.env` 中。上传的原始文件默认保存在 `/opt/tarsgo-knowledge`，位于仓库之外的私有目录。单文件限制 10 MiB。PDF 只做文本提取，不使用 OCR；没有可提取文本的文件会被标记为相应状态。

提取后的文本和来源元数据索引在 `knowledge_documents` 中。GitHub 路径按 source path 与 content hash 执行 upsert；缺失文件会标记为 removed。本地检索会按标题、路径和正文关键词评分，并自动发送最多六段短历史摘录，历史文本总计最多 3,000 字符。Planner UI 不暴露 Knowledge 来源搜索或历史详情。粘贴文本与 Planner 临时提取的附件拥有独立的 5,000 字符预算，并具有更高优先级；Planner 附件绝不会创建 Knowledge 记录，也不会持久化到 Knowledge 存储目录。自动检索到的历史内容绝不会被当成当前活动事实：旧日期、地点、人物和数量不能直接套用到当前活动。文档仅作为不可信参考文本，不作为指令。系统不使用 embedding、向量数据库或基于模型的检索。

服务端配置：

~~~text
KNOWLEDGE_ENABLED=false
KNOWLEDGE_GITHUB_REPO=owner/repository
KNOWLEDGE_GITHUB_BRANCH=main
KNOWLEDGE_GITHUB_TOKEN=<read-only fine-grained token, if required>
KNOWLEDGE_GITHUB_PATHS=docs,knowledge
KNOWLEDGE_STORAGE_HOST_DIR=/opt/tarsgo-knowledge
~~~

对于私有仓库，应使用仅限制到该仓库、且 Contents 权限为只读的 fine-grained token。不要将 token、上传文件或私有战队材料提交到 Git，或写入普通日志。API 永远不会返回文档正文、服务端文件系统路径或 GitHub 凭据。

## 本地运行

~~~bash
cp .env.example .env
docker compose up -d --build
~~~

打开 http://localhost。

本地 HTTP 配置：

~~~text
APP_DOMAIN=:80
SESSION_COOKIE_SECURE=false
~~~

API 容器会在 FastAPI 启动前执行 alembic upgrade head。

## 创建第一个管理员

系统不提供公开注册入口。

~~~bash
docker compose exec api python -m app.bootstrap_admin
~~~

第一个管理员随后可以在 /team 邀请其余账号。

## 前端开发

依赖通过 package-lock.json 锁定。

~~~bash
cd frontend
npm ci
npm run build
npm run dev
~~~

## RackNerd 部署准备

单台 VPS 位于已有 Nginx 服务之后时：

~~~text
APP_DOMAIN=your-domain.example
CADDY_SITE_ADDRESS=:80
WEB_BIND_ADDRESS=127.0.0.1
WEB_HTTP_PORT=8080
SESSION_COOKIE_SECURE=true

MYSQL_DATABASE=tarsgo
MYSQL_USER=tarsgo
MYSQL_PASSWORD=<strong-random-password>
MYSQL_ROOT_PASSWORD=<strong-random-password>
~~~

然后执行：

~~~bash
docker compose up -d --build
~~~

只对外发布 web 容器的 HTTP 端口。FastAPI 和 MySQL 保持在 Docker 内部网络中。MySQL 数据保存在命名卷 mysql_data 中。

## 验证

新增的虚构活动演练使用 8 名模拟成员和 5 项分工，覆盖并发认领、依赖阻塞、地点变更、换人交接、权限、AI 失败后的进展持久化及事项完成。CI 还会把数据库及知识原件恢复到全新的数据卷并验证内容及登录。操作说明见 [备份与恢复](docs/backup-and-restore.md)。

GitHub Actions 执行：

~~~bash
cd frontend
npm ci
npm run build
~~~

以及：

~~~bash
docker compose up -d --build
python scripts/smoke_test.py workflow http://127.0.0.1
python scripts/smoke_test.py persistence http://127.0.0.1
~~~

覆盖范围包括：

- member 对全部已发布运营任务的可见性
- 父 / 子关系正确性与单层限制
- 直接分配与公开负责人认领
- 原子地防止重复认领
- 开放协作加入 / 退出
- 安全取消认领
- admin / manager 重新分配
- member 结构编辑限制
- 仅 admin 可访问的 Knowledge API、支持的文本提取、文件大小限制、GitHub 路径 / hash 同步、来源移除处理与有边界的 Planner 检索
- Planner 仅调用一次 provider，并在知识索引不可用时优雅运行
- 负责人 / 协作者进展、仅负责人完成、依赖校验与确定性的根事项状态聚合
- 单次 AI 事实建议、人工批准与共享配额记账
- disabled 成员阻断
- 数据库重启后的持久化
- V0.1 旧数据迁移
- 所有 active admin 的 AI Planner 鉴权
- 缺失 AI 配置与超长输入
- mock 的单次结构化草稿生成且不写入任务
- 可编辑草稿确认与原子批量回滚
- 持久化 AI 请求 / token 记账
- mock 的 OpenAI parse 路径，以及 DeepSeek create + json_schema + Pydantic 校验路径

## 明确暂缓

V0.2 第一阶段**不会**实现：

- AI 自动排期
- AI 成员选择 / 人员推荐
- 自动排期
- 时间冲突计算
- 任务推荐算法
- 工作量算法
- 通知
- 评论
- 文件
- 请假
- 周报
- 技术研发管理
- 复杂仪表盘
- 复杂组织结构
- 完整字段变更历史

后续 AI 与更丰富执行元数据的产品方向已经记录在文档中，但目前尚未实现。

## 公共仓库边界

本仓库为公开仓库。绝不要提交：

- .env
- 密码、凭据、session token、invite token、API key 或私钥
- VPS IP 地址或其他私有服务器信息
- 数据库文件或备份
- 真实成员姓名、邮箱地址、学号、手机号或内部战队材料

测试和文档使用张三、李四、admin@example.com、lisi@example.com 等虚构身份。

不希望个人 Git 邮箱暴露在 commit 元数据中的贡献者，应在提交前配置 GitHub 提供的 noreply 地址。已有 Git 历史不会重写。

## 生产环境测试数据清理

不要通过 migration 或应用启动流程自动删除生产数据。

V0.2 部署后，如需清理生产环境中的虚构测试数据，应单独进行经过审查的数据库操作，并满足：

1. 使用明确的 ID / 邮箱 / 标题识别虚构账号和任务
2. 保留数据库 schema 和 Alembic 版本
3. 保留真实管理员账号
4. 删除虚构成员之前，先删除依赖的 task-collaborator 记录、任务、session 和 invitation
5. 在备份后，于事务中执行
6. 执行前完成审查

本版本不会执行任何生产数据清理。

## License

MIT
