# PrintLabInterface · INDEX（状态与交接总表）

> 用途：新的上下文只读本文件即可恢复全部状态并继续推进。每完成一个阶段或做出新决定，先更新本文件再继续。
> 最后更新：2026-11-17（系统时间）。本文件不含任何密钥、访问码、IP、序列号。

---

## 0. 快速恢复（先读这一节）

- 当前位置：**P0、P1 全部完成并通过 G1–G4。下一阶段 P2（供应商与模型）。** P2 的真实供应商调用需要用户自己填入 API key，开始 P2 前要先问用户。
- 最近一次 G1–G4 实测（P1 验收，2026-11-17，**sidecar 运行中与真正停掉后各测一次**）：G1 PrintLab `git status` 为空；G2 pytest 446 通过 / 42 跳过 / 7 失败，与基线一致（同样 7 个符号链接用例）；G3 `verify_onboarding` ok:true、`/api/health` ok:true、`doctor` 四工具可用且 `missing_context` 为空；G4 摘除 sidecar（确认 8019 无监听、无 printlab_interface 进程）后 G1–G3 仍全部通过，反向实测 sidecar 在 `PLI_PRINTLAB_ROOT=""` 且 PrintLab 地址不可达时仍能启动并返回 `/healthz` ok。**踩过的坑**：`kill $!` 在 Windows 下没有真正结束 uvicorn 子进程，必须用 PowerShell `Stop-Process` 并复核端口，否则 G4 是假的（本次第一轮 G4 数据因此作废并重测）。
- P0-3 结论：**采用 LiteLLM + LangGraph，进入 P1**；详见 `docs/SPIKE_P0_3.md`。注意：模型调用只用了 `mock_response`，**没有任何真实供应商调用被验证**。
- **必读的坑**：调用 PrintLab CLI 时，子进程环境变量白名单太窄会导致"退出码 0 但输出为空"，并在当前工作目录创建名为 `%SystemDrive%` 的垃圾目录，使 PrintLab 的 `git status` 变脏（违反 G1）。已在临时目录复现并确认因果，白名单必须包含 `SYSTEMDRIVE`、`PROGRAMDATA`、`WINDIR` 等（完整清单见 `docs/spike_p0_3.py` 的 `ENV_ALLOW`），子进程 `cwd` 不得设为 PrintLab 根。
- 下一步动作：P0-4 复核 G1–G4；然后进入 P1（只读适配器），按 `docs/SPIKE_P0_3.md` §5 的四条要求实现。
- 硬规则：不修改 `E:\MyProjet\PrintLab` 下任何文件；不调用 approve / submit --execute / reconcile / studio-bridge 发送类命令；未经用户明确要求不 commit、不 push。
- 回复语言：始终使用简体中文。
- 用户称呼：cuckoo。

---

## 1. 项目背景与最终目标

### 1.1 背景
- **PrintLab**（AFangTeam / 阿方 Eric，v0.4.4，PolyForm Noncommercial 1.0.0）是 3D 打印工作台：从想法到实物的流程（需求、概念图、三视图、CAD、切片对比、材料、批准、打印、复盘），Python + FastAPI 后端，React 前端，CLI 为 `Harness\bin\printlab.ps1`。
- PrintLab **本身不含任何 AI 调用**（已查证后端与前端代码）。智能全在外部 Agent（Codex、NarraFork 等）。
- 用户目前主要用 Codex 及内置助手操作，希望改为**自建编排层**，通过调用现成模型 API（OpenAI、Claude、DeepSeek 等）实现所有 AI 能力，可依赖第三方编排框架（须核实开源许可）。

### 1.2 最终目标
建设 **PrintLabInterface**：一个独立仓库、独立进程（Sidecar）的 AI 编排服务，提供：管理后台、聊天台、供应商配置、代理（Agent）管理、工作流。以松耦合方式挂载到 PrintLab 之上。

### 1.3 必须满足的集成原则（用户硬性要求）
1. 对 PrintLab 只做**加法**，不修改、不删除、不重构原有逻辑。
2. 所有新功能以 Sidecar / 反向代理等松耦合方式存在。
3. 两者关系是**并集**：摘掉 PrintLabInterface，PrintLab 完全不受影响；移除 PrintLab，PrintLabInterface 仍能独立启动。
4. 旧项目完全不感知新仓库（依赖单向：新 → 旧）。

### 1.4 我方追加的安全红线（不可配置）
- 适配器**永久拒绝**：`approve`、`submit`（含 `--execute`）、`reconcile`、`studio-bridge` 发送类命令、HTTP 的 `/api/prepared/*` 全部 POST。理由：打印批准绑定物理清板确认，AI 无法验证；H2C 固件对第三方命令敏感。
- 写 PrintLab 数据只能经 `printlab` CLI（带 SHA 版本检查与 request-id），不得直接写旧项目文件。
- 子进程环境变量用白名单；日志脱敏；所有队列、输出、超时有上限。

---

## 2. 已知关键信息

### 2.1 本机环境（CUCKOO）
| 项 | 值 |
| --- | --- |
| 系统 | Windows 11 专业版 10.0.26200，x64，AMD Ryzen 9 9950X，64 GB，RX 9070 XT |
| Python | 3.13.13（conda：`D:\Users\30386\miniconda3\python`） |
| Node / npm | v24.19.0 / 11.17.0 |
| Git | 2.56.0.windows.2；**PrintLabInterface 仓库未配置 user.name/email**（见 §5） |
| Bun / Java / Rust | 未安装 |
| Shell 注意 | Bash 工具走 Git Bash；不要用 findstr、dir 等 cmd 内置命令；没有 `py` 启动器，`python3` 命令也不存在（用 `python`） |
| 用户硬要求 | Python 虚拟环境必须建在项目目录内，**不污染系统 Python** |
| 完整硬件说明 | 个人知识库条目 `EzNzwwjxJ78jfuGhKRGVd`（CUCKOO 本机硬件配置与开发环境） |

### 2.2 PrintLab（旧项目）
- 路径：`E:\MyProjet\PrintLab`，HEAD `d0484b6` = 标签 v0.4.4，`git status` 干净（G1 基线）。
- 虚拟环境：`Runtime\venv`（Python 3.13.13）；已 setup 完成。
- 工作台：`http://127.0.0.1:8018`，仅监听 127.0.0.1。**由本会话后台启动，会话结束或重启电脑后需手动重启**：`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1`（在 PrintLab 目录）。
- CLI（Windows）：`powershell -NoProfile -ExecutionPolicy Bypass -File ./Harness/bin/printlab.ps1 <子命令>`；需 `PYTHONUTF8=1`；成功退出码 0，失败退出码 2，错误 JSON 在 stderr。
- 被 gitignore 的本机数据：`Runtime/`、`Project/`、`Library/Devices/*`、`Context/profile.md|taste.md|agent-policy.json|team.md`。这些已被写入用户配置，**不要重新初始化**。
- 基线（2026-11-17 记录）：
  - `pytest Harness/tests`：**446 通过、42 跳过、7 失败**。7 个失败全部是 `WinError 1314`（Windows 账号无创建符号链接权限），属环境原因，不是代码缺陷：test_api、test_backup、test_onboarding、test_publication（2 个）、test_shop、test_workflow 各涉及符号链接的用例。开启 Windows 开发者模式后可重跑。
  - `node --test Harness/tests/native-inspection.test.mjs`：同样因符号链接 `EPERM` 失败，未得到结果。
  - `scripts/verify_onboarding.py`：`ok: true`。
  - `/api/health`：`{"ok":true,"version":"0.4.4","read_only":false,"features":[...6项]}`。
  - `printlab doctor`：slicer、blender、cad_python、检查器均可用，无 missing_context；`printer_configured` 在初始化时为 false（设备卡之后已填写）。
- **HTTP 路由全清单（P0-1 成果，live openapi 核对）**：
  - GET（只读）：`/api/health`、`/api/overview`、`/api/device`、`/api/projects`、`/api/projects/{pid}`、`/api/projects/{pid}/confirmation`、`/api/library`、`/api/shop`、`/api/history`、`/api/onboarding`、`/api/documents/{relative}`、`/api/files/{pid}/{relative}`、`/api/prepared`、`/api/prepared/session`、`/api/prepared/operations/{opid}`、`/api/prepared/sender/capability`，以及静态资源 `/assets`、前端兜底 `/{path}`。
  - **POST（全部是危险面，适配器永久拒绝）**：`/api/prepared/{pid}/{jid}/check`、`/api/prepared/{pid}/{jid}/start`、`/api/prepared/operations/{opid}/reconcile`、`/api/prepared/sender/enable`。
  - 结论：旧项目 HTTP **没有任何适合外部写入的接口**，写入一律走 CLI。
- 重要 CLI 子命令（来自 `Harness/printlab/cli.py`）：读类 `status`、`context`、`materials`、`dispatch-plan`、`doctor`、`history`、`prepared list/check`、`workspace show/profiles/connection`；写文件类 `new`、`build`、`export-project`、`slice`、`handoff`、`review`、`workspace note/device/profile/connect`、`record-confirmation`、`constraints capture`、`shop confirm/sync/stock/...`、`material-intake`、`taste record`、`design-check`；**禁止类** `approve`、`submit`、`reconcile`、`retry`、`register-cancel`、`studio-copy`（会准备发送包）、`studio-bridge`。
- 文档入口：`AGENTS.md`、`docs/AGENT_START.md`、`docs/PRINTING.md`、`docs/CONNECTIONS.md`、`Context/workflow.md`。

### 2.3 打印机与相关工具
- 打印机：**H2C**，在 Bambuddy 中 ID=1，名称 `3DP-H2C`，固件 01.03.00.00，开发者模式未开，SD 卡可用。局域网另有一台 `3DP-X1C`，**用户未要求添加，未添加**。
- 喷嘴：左右挤出机均读回 0.4 mm（HS01）；喷嘴架里有一枚 0.6 mm（HS01）。**默认按 0.4 mm；0.6 mm 仅在用户需要时才换上，选 0.6 预设前必须先问。**
- 供料（用户确认）：挤出机 0 对应两个 AMS 2 Pro（AMS 0、1）；挤出机 1 对应一个 AMS HT（AMS 128）。用户说的"左"是面向机器的方向，等于机器自己的"右"；记录统一用**挤出机编号**。
- 发送路线：`dispatch-plan --model H2C --feeding ams` 结论是 **official_studio**（Bambuddy 队列适配只覆盖 A1、A1 mini、P1S、X1 Carbon）。H2C 的发送由用户在官方 Studio **手动点击**；Windows 无 Studio 窗口助手。
- Bambu Studio 02.09.01.70：`D:\Program Files\Bambu Studio`（含 H2C 0.2/0.4/0.6/0.8 官方预设）。比文档验证过的 02.08.02.61 新。
- Blender 5.3.0：`D:\Program Files\Blender Foundation\Blender 5.3\blender.exe`。
- Bambuddy 1.3.1：`D:\Program Files\Bambuddy`，服务 `http://127.0.0.1:8000`（不是 PrintLab 默认的 8017），**未启用认证**。比文档验证过的 1.2.5.7 新。
- PrintLab 访问 Bambuddy 用专用只读 key（名称 `PrintLab read-only`，仅 `can_read_status`），存放在 `PrintLab\Runtime\private\bambuddy.json`（已 gitignore）；`write_api_key` 为空。**打印机访问码只存在于 Bambuddy 自己的数据库，不得写入任何文件或文档。**
- 已写入：`PrintLab\Runtime\config.json`（路径与 `bambuddy_url`、`printer_id=1`）、设备卡 `Library/Devices/X2D/device.json`、`installed.md`、`Context/profile.md`（偏好笔记，request-id `h2c-nozzle-pref-20261117`）。
- 设备读回的未解事项：HMS `0x10007`（MQTT 命令验证失败，提示更新 Studio 网络插件或 Handy，关联旧任务）。耗材余量为账面估算。

### 2.4 参考项目 NarraFork（第一步调研结论）
- 仓库：https://github.com/NarraFork/NarraFork，调研提交 `eeb30f9`（2026-11-16），**MPL-2.0**（文件级弱 copyleft）。Bun + TypeScript + Hono + Drizzle + React，SQLite。
- **决定：只借鉴设计，不拷贝源码。** 复制其源文件会使这些文件须继续以 MPL 开源。
- 本地临时克隆：`/tmp/ref/NarraFork`（236 MB，Git Bash 的 /tmp，可能被清理）。重取：`git clone --depth 1 https://github.com/NarraFork/NarraFork.git` 然后 `git checkout eeb30f9`（深度为 1 时需先 `fetch` 该提交）。是否保留待用户答复（见 §5）。
- 重点文档：`docs/AGENT_PROVIDERS.md`、`docs/plugin-system/`（00 总览、02 宿主架构、03 Manifest、11 能力策略）、`docs/OPEN_API.md`。
- 值得借鉴（映射到我们）：

| 能力 | NarraFork 模式 | 我们的做法 |
| --- | --- | --- |
| 供应商 | `ProviderAdapter` 统一接口 + `前缀:模型` ID + 多 key 池与失败分类（401 失效、402/额度 429 冷却 30 分、403 冷却 10 分、其他 429 按 Retry-After、5xx 不惩罚 key）+ 就绪状态与路由同注册 | 保留接口、前缀 ID、key 池；适配器用现成库，不手写、不做缓存前缀与延迟工具加载 |
| 模型管理 | 模型卡：目录 < 自动发现 < 用户覆盖（整模型/单供应商条目两级）；"未知不等于零"；卡里禁止带密钥类字段 | 保留三层合并，先只做必要字段 |
| Agent | `SUBAGENT.md`（frontmatter：name、description、toolAccess、customTools、defaultModel；正文为提示词）编译成**能力天花板**；被委派者默认无编排权；只能收紧不能放宽；非法定义退化为只读 | 直接采用，对应 Sarah、Mike、任务组，并增加"允许的 printlab 命令"白名单字段 |
| 搜索 | 渠道抽象（native / 网关 / 自定义 API / 搜索子 Agent）、超时、输出截断、搜索运行时不得递归进入渠道路由、强制来源引用 | 只读搜索工具，先不做子 Agent |
| 多 Agent 通信 | 持久邮箱（`user_input`/`agent_message`/`task_notice`，`sourceKey` 幂等回执，`claim` 令牌与 epoch 可恢复）；`Send`/`Await`/`ContextAsk`/`TeamStatus` | 用 SQLite 表实现邮箱与幂等 |
| 工作区/容器 | worktree；rootless Podman 仅 Linux；沙箱策略限制 UID/内存/进程/CPU 并**不继承**宿主环境凭据 | **不采用**容器（Windows 不可用）；借鉴环境变量白名单与原子写配置 |
| 扩展 | Manifest/Contribution/Activation、一插件一进程、Content-Length 分帧 JSON-RPC over stdio、三层版本（manifest/Host API/RPC）、插件不得 import 宿主内部 | 作为 Sidecar 设计参考，不实现插件宿主 |
| 能力策略 | 先做 66 项逐项授权，发现无运行时消费方后改"安装即信任"，**但保留全部存活类限制**（输出大小、超时、队列上限） | 借鉴：安全红线靠"物理不可达"，存活限制全部保留 |
| 对外 API | OAuth2 + PKCE，External API v1 与内部路由身份隔离，非本 grant 资源返回 404 | 第一版只绑 127.0.0.1 + 本机 token，后续再升级 |
| 工作流编排 | **NarraFork 没有 DAG 引擎**（"routine"只是命令/技能/工具开关；"pipeline"是工具输出文本管道）。靠主 Agent 动态决策 + 任务清单 + 计划模式 + 反思门 | 自建**显式状态机**（PrintLab 流程阶段固定） |

### 2.5 第三方框架许可核实（读 LICENSE 原文，非仅 SPDX 标签）
| 框架 | 许可 | 备注 |
| --- | --- | --- |
| LiteLLM | MIT（核心）；`litellm/enterprise/` 目录另有商业许可 | 只能当库用，**禁用 enterprise 目录**与 proxy 的企业特性。GitHub API 显示 NOASSERTION 是因为 LICENSE 为混合声明 |
| Vercel AI SDK | Apache-2.0 | TypeScript 生态，本方案不用 |
| LangGraph | MIT | 状态机与检查点、人工中断 |
| OpenAI Agents SDK | MIT | 多供应商支持待核实 |
| PydanticAI | MIT | 类型化 Agent |
| MCP Python SDK | MIT | 可选 |
| FastAPI | MIT | 已在用 |
| Starlette | BSD-3-Clause | |
| Temporal / Prefect | MIT / Apache-2.0 | 太重，不采用 |

**P0-3 实测版本（2026-11-17，已装进 `.venv`）**：litellm 1.109.1（MIT，`enterprise/` 目录未安装）、langgraph 1.2.22、langgraph-checkpoint 4.3.2、langgraph-sdk 0.4.14、langchain-core 1.8.1（均 MIT）、openai 3.51.0（Apache-2.0）、pydantic 2.14.3、tiktoken 0.14.0、tokenizers 0.23.3（元数据 License 字段为空，Classifier 为 Apache）。全环境 90 个包，元数据关键字筛查无 GPL/AGPL/SSPL 等命中。**但 litellm、langgraph 尚未写入 `pyproject.toml`，也没有锁定文件。**

**仍未核实**：真实供应商调用（OpenAI/Claude/DeepSeek）、LangGraph 检查点与 `interrupt`、并发与取消行为、传递依赖的完整许可审查（元数据筛查只是粗筛）。P6 用锁定版本跑正式许可扫描（如 `pip-licenses`）并人工核对缺字段的包。

---

## 3. 已确认的决策

| 决策 | 结论 | 日期 |
| --- | --- | --- |
| 仓库布局 | **方案 A：同级兄弟目录**。`E:\MyProjet\PrintLab` 原地不动，新仓库 `E:\MyProjet\PrintLabInterface`（独立 git）。未采用 B（嵌套）与 C（搬入 `legacy/printlab/`） | 2026-11-17 用户确认 |
| 语言栈 | **Python + FastAPI + SQLite** | 2026-11-17 用户确认 |
| 先做 P0 Spike | 是 | 2026-11-17 用户确认 |
| 挂载方式 | **Sidecar（独立进程，端口 8019，只绑 127.0.0.1）为主**；反向代理（`/` 转旧工作台、`/ai/` 转新服务）作为可选统一入口，P5 再做 | 方案推荐，用户随选项确认 |
| 读写通道 | 读：HTTP 127.0.0.1:8018 + CLI 读命令；写：**仅 CLI 白名单** | 同上 |
| 协议 | 浏览器：HTTP + SSE；Agent 间：SQLite 邮箱；不用 gRPC、不用外部消息队列 | 同上 |
| 为何不选插件/中间件 | 需要改旧项目启动代码或加插件宿主，违反"不修改" | 同上 |

### 3.1 为什么没采用"把 PrintLab 搬进 legacy/printlab"
PrintLab 的 `Runtime/venv` 写入了绝对路径（搬动后 venv 失效需重建）；`.agents/skills`、CI、`core.ROOT` 都按仓库根解析；工作台服务正占用目录。这与"保持原路径引用不被破坏"冲突，且违背"旧项目不动"。用户选了 A，方案 C 不再考虑，除非用户另行提出。

---

## 4. 进展状态

### 4.1 已完成
**PrintLab 初始化（本会话前半段）**
- [x] 阅读项目文档与代码结构，向用户汇报。
- [x] `setup.ps1`：`Runtime/venv`、npm 依赖、前端构建、工作区初始化、离线检查器 bambu-printer-mcp 1.1.33 全部完成。
- [x] 在 D 盘找到 Studio、Bambuddy、Blender，修正 `Runtime/config.json`。
- [x] 用 SSDP 无果后改子网扫描，找到 H2C，添加到 Bambuddy（ID 1），建立只读 key，PrintLab 可读状态与耗材。
- [x] 设备卡、`installed.md`、`Context/profile.md` 已写入并经用户确认（含 AMS 左右澄清、0.4 默认）。
- [x] 工作台启动并验证 `/api/health`。

**PrintLabInterface 方案阶段**
- [x] 第一步：NarraFork 调研报告（本文 §2.4、§2.5 为摘要）。
- [x] 第二步：仓库布局方案（§3）。
- [x] 第三步：集成原则（§1.3、§1.4）。
- [x] 第四步：集成技术方案（§6）。
- [x] P0-1：旧项目基线与 HTTP 路由全清单（§2.2）。
- [x] P0-2：新仓库骨架（独立 git、`pyproject.toml`、包目录、`.venv`）。
- [x] P0-3：Spike（`docs/SPIKE_P0_3.md`）：采用 LiteLLM + LangGraph；模型调用仅 mock。
- [x] P0-4：G1–G4 复核通过。
- [x] **首次提交并推送**：`0c8a2bd`，作者 `cuckoo711 <3038604221@qq.com>`（来自本机环境变量 GIT_AUTHOR_*，未改 git config）。远端 `origin` = `git@github.com:cuckoo711/PrintLabInterface-.git`（注意仓库名末尾有一个 `-`），分支 `main`。
- [x] **P1 只读适配器与骨架**：
  - `config.py`：环境变量 `PLI_*`；只允许回环地址；`PLI_PRINTLAB_ROOT=""` 表示不使用 PrintLab。
  - `redact.py`：日志与审计脱敏（sk-、bb_、Bearer、api_key/access_code/password/token=、192.168.x.x）。
  - `db.py`：自有 SQLite（WAL），`meta` 与 `audit` 两表。
  - `adapters/printlab/policy.py`：三层策略（READ / WRITE / NEVER），NEVER 无条件拒绝且优先；HTTP 只 GET 且路径白名单，`/api/prepared*` 永久拒绝；拒绝 `--execute/--send/--start`。
  - `adapters/printlab/runner.py`：子进程执行器（环境白名单、`cwd`=自己的 `data/run`、超时、输出上限、并发上限 2、空输出视为错误、调用前后比对 PrintLab 的 git 状态，读调用改动树或写调用留下未跟踪文件即拒绝后续写调用）。
  - `adapters/printlab/http.py`、`adapter.py`：只读 HTTP、能力探测、离线降级。
  - `app.py`、`__main__.py`：`/healthz`、`/api/printlab`、`/api/printlab/status`、`/api/audit`；端口 8019；PrintLab 缺失仍可启动。
  - 测试 90 个（`tests/test_policy.py`、`test_runner.py`、`test_app.py`），全部通过。

### 4.2 进行中
- 无。下一步 P2 需要先问用户要不要现在开始、以及用哪几家供应商（key 由用户自己填入）。

### 4.3 当前仓库文件导航（PrintLabInterface）
```
E:\MyProjet\PrintLabInterface\
├─ INDEX.md                         本文件
├─ pyproject.toml                   fastapi、uvicorn、httpx、litellm>=1.109,<2、langgraph>=1.2,<2；test: pytest；脚本 printlab-interface
├─ .gitignore                       忽略 .venv、data/*（保留 .gitkeep）、config/*.local.*、.env*
├─ .venv\                           独立虚拟环境（不进 git）
├─ docs\SPIKE_P0_3.md、spike_p0_3.py   P0-3 结论与可重跑脚本
├─ src\printlab_interface\
│   ├─ __init__.py（版本 0.1.0）  __main__.py  app.py  config.py  db.py  redact.py
│   ├─ adapters\printlab\            ★ 唯一允许知道 PrintLab 的地方：policy.py runner.py http.py adapter.py
│   └─ providers\ agents\ tools\ workflows\   仍是空包（P2 起填充）
├─ config\agents\  config\workflows\          空
├─ tests\                           conftest.py test_policy.py test_runner.py test_app.py（90 个）
└─ data\                            interface.db、run\（运行时产生，已 gitignore）
```

---

## 5. 未解决问题、风险与待确认项

### 5.1 待用户确认
1. **NarraFork 临时克隆（`/tmp/ref/NarraFork`，236 MB）保留还是清理？** 尚未回答；默认暂不删除。
2. ~~Git 身份~~：已解决。环境变量 GIT_AUTHOR_*/GIT_COMMITTER_* 已提供身份（cuckoo711），用户已明确要求提交并推送，且给出了两个远端地址。
3. 许可：PrintLabInterface 本身用什么许可？尚未决定。不得拷贝 PrintLab 代码或文档（其为 PolyForm Noncommercial，需保留署名与非商用条款）；文档里标注对 PrintLab 的运行时依赖。
4. 开启 Windows 开发者模式后重跑 PrintLab 测试，把 7 个符号链接用例纳入基线？（需要用户在系统设置中操作。）
5. 模型供应商的 key（OpenAI、Claude、DeepSeek 等）由用户自己填入，我不接触。何时进入 P2 由用户决定。

### 5.2 技术未知项（需要在 P0 Spike 或后续阶段验证）
- LiteLLM + LangGraph（及可选 PydanticAI / OpenAI Agents SDK）版本兼容、工具调用在不同供应商（尤其 DeepSeek）上的格式差异、传递依赖许可。**退路**：自写极小状态机（阶段固定、不超过十来个）。
- PrintLab 子命令的 JSON 输出稳定性、各读命令耗时（子进程调用开销）。
- 旧项目 `/api/health.features` 是否足以做"能力探测"。
- 旧工作台前端是已构建的静态包，**无法插入新页面**；新功能走独立页面（8019），统一入口靠 P5 的反向代理。

### 5.3 风险清单
| 风险 | 缓解 |
| --- | --- |
| 提示注入（模型文件名、Bambuddy 文本、搜索结果夹带指令） | 危险命令在适配器层物理不可达，不靠提示词 |
| 密钥泄露 | DPAPI/keyring 加密，日志脱敏，只绑 127.0.0.1 |
| 旧项目升级后接口变化 | 能力探测 + 契约测试，失败降级为"离线" |
| H2C 固件对第三方命令敏感（HMS 0x10007） | 不规划任何绕开 Studio 的发送 |
| 版本漂移：Studio 02.09.01.70、Bambuddy 1.3.1 均高于文档验证版本 | 自动化前先做契约测试；兼容问题如实上报 |
| 供应商工具调用格式差异 | 模型卡能力位 + 调用前能力检查 + 回归提示集 |
| 成本失控 | 每次运行 token 上限、每日预算、用量告警 |
| 端口冲突 | 固定 8019，启动前探测；已占用端口：8018（PrintLab）、8000（Bambuddy，另有进程 PID 5000 监听 8000，即 Bambuddy） |
| 框架组合不稳 | Spike + 许可扫描 + 自写状态机退路 |
| 后台工作台服务随会话结束 | 重启命令见 §2.2 |

---

## 6. 技术方案摘要（第四步）

### 6.1 接口
- **PrintLab 无需新增任何扩展点**（设计目标）。适配器只用 §2.2 列出的 GET 路由与 CLI 读/写命令。
- **PrintLabInterface 计划提供**（127.0.0.1:8019）：`/api/providers`（供应商 CRUD、key 池、连通测试）、`/api/models`（模型卡）、`/api/agents`（角色定义与能力天花板预览）、`/api/chat`（会话与 SSE）、`/api/workflows`、`/api/runs`（审计）、`/api/tools`、`/api/printlab`（适配器状态，只读代理）、`/healthz`。

### 6.2 子进程调用 PrintLab CLI 的约束
`powershell -NoProfile -ExecutionPolicy Bypass -File <PrintLab>\Harness\bin\printlab.ps1`；`PYTHONUTF8=1`；按 UTF-8 解码；超时、输出上限、并发上限；环境变量白名单；退出码 2 视为失败并解析 stderr JSON。

### 6.3 数据层隔离
| 数据 | 归属 | 访问 |
| --- | --- | --- |
| 项目、设备卡、偏好、材料、handoff | PrintLab（`Project/`、`Library/`、`Context/`） | Interface 只读，写走 CLI |
| Bambuddy 数据 | Bambuddy 自己的库 | Interface 不直连 |
| 供应商、密钥、模型卡覆盖、会话、审计、邮箱、运行状态 | Interface（`data/interface.db`，SQLite） | 仅 Interface |
| 角色定义、工作流定义 | Interface（`config/agents/*.md`、`config/workflows/*.yaml`，进 git） | 仅 Interface |
- 两个数据库不共享表、不跨库外键；引用旧项目对象只存稳定标识（项目 ID 如 `P001`、文件 SHA、`latest_session`），每次重新读，不把缓存当权威。
- 密钥不用明文 JSON（旧项目的明文是它的现状，不照抄）。

### 6.4 候选技术栈（待 Spike 确认）
LiteLLM（多供应商调用，仅库、不用 enterprise）+ LangGraph（显式状态机、检查点、人工中断）；Agent SDK（PydanticAI 或 OpenAI Agents SDK）视 Spike 结果再决定；MCP SDK 可选。

### 6.5 统一验收门槛（每个阶段都要过）
- **G1**：`git -C E:\MyProjet\PrintLab status --short` 输出为空。
- **G2**：PrintLab `Runtime\venv\Scripts\python.exe -m pytest Harness/tests -q` 与基线一致（446 通过 / 42 跳过 / 7 个符号链接失败）。
- **G3**：`verify_onboarding.py` 返回 `ok: true`；`/api/health` 为 `ok: true`；`printlab doctor` 无新增缺失项。
- **G4（摘除测试）**：停掉 Interface 进程后，G2、G3 仍全部通过。
- 额外（P4 起）：确认旧项目没有出现未经 `printlab` 命令的文件改动。

---

## 7. 待办清单（优先级与完成标准）

| ID | 优先级 | 事项 | 完成标准 |
| --- | --- | --- | --- |
| P0-3 | 已完成 | Spike：LiteLLM + LangGraph 两节点图 | 已跑通（模型调用仅 mock）；结论见 `docs/SPIKE_P0_3.md`：采用 LiteLLM + LangGraph |
| P0-4 | 已完成 | 复核 G1 到 G4 | 四项实测通过，见 §0 |
| P1 | 已完成 | 骨架与只读适配器（见 §4.1） | 90 个单测通过；实服务对真实 PrintLab 读到 H2C 状态；G1–G4 通过 |
| P2 | 中 | 供应商与模型：CRUD、加密存储、key 池与失败分类、连通测试、模型卡三层合并、调用封装（取消、推理档位、输出上限、结构化输出）、用量记录 | 用户填入 key 后 OpenAI/Claude/DeepSeek 各完成一次真实调用；key 不出现在日志；G1–G4 |
| P3 | 中 | 代理与聊天台：角色定义文件 + 权限天花板；工具网关（读、写文件类白名单）；Agent 循环；SSE 聊天前端；审计页；只读搜索工具 | Sarah、Mike 可对话并调用 status/materials/context；越权调用被拒并记录；会话可恢复；G1–G4 |
| P4 | 中 | 工作流与协同：显式状态机（需求到复盘）、"待人选择"与"待批准"硬停点、SQLite 邮箱、只读巡检角色、定时触发 | 一次完整小物件流程跑到"待批准"为止；中途杀进程可恢复；重放不重复建项目；G1–G4 + 无越权文件改动 |
| P5 | 低 | 管理后台页面；可选反向代理（`/` 与 `/ai/`）；备份与导出 | 后台可管理供应商、角色、工作流；代理开关不影响旧入口；G1–G4 |
| P6 | 低 | 稳定化：许可扫描、依赖锁定、文档、可选 Windows 服务化 | 全新机器按文档可安装；许可清单完整 |

---

## 8. 文档与资源导航

| 需要什么 | 去哪里 |
| --- | --- |
| 本项目全局状态 | 本文件 `INDEX.md` |
| PrintLab 总览 | `E:\MyProjet\PrintLab\README.md`、`AGENTS.md` |
| PrintLab 安装与首次配置 | `PrintLab\docs\AGENT_START.md`、`SETUP.md`、`WINDOWS.md`、`FIRST_RUN.md` |
| 打印路线与批准规则 | `PrintLab\docs\PRINTING.md`、`Context\workflow.md`、`Context\official-studio-dispatch.md` |
| 机型验证范围 | `PrintLab\docs\MACHINE_SUPPORT.md`（不含 H2C） |
| Bambuddy 连接 | `PrintLab\docs\BAMBUDDY_SETUP.md`、`CONNECTIONS.md` |
| 设备卡与工具版本 | `PrintLab\Library\Devices\X2D\device.json`、`installed.md`（已 gitignore，本机文件） |
| 用户偏好 | `PrintLab\Context\profile.md`（本机文件） |
| PrintLab 后端入口 | `PrintLab\Harness\printlab\api.py`、`cli.py`、`prepared_api.py`、`workspace.py` |
| NarraFork 参考 | `/tmp/ref/NarraFork`：`docs/AGENT_PROVIDERS.md`、`docs/plugin-system/*`、`docs/OPEN_API.md`；`server/lib/agent/provider.ts`、`credential-pool.ts`、`pooled-provider.ts`；`server/services/agent-runtime/policy.ts`、`mailbox*.ts`；`server/services/custom-subagent-service.ts`；`shared/model-catalog/*` |
| 本机硬件 | 个人知识库 `EzNzwwjxJ78jfuGhKRGVd` |
| 任务清单（会话内） | `spec://tasks.json`（会话级，不在磁盘；以本文件 §7 为准） |

### 8.1 常用命令速查
```bash
# PrintLab 基线检查（Git Bash，在 E:\MyProjet\PrintLab）
git status --short                                   # 必须为空
curl -s http://127.0.0.1:8018/api/health
export PYTHONUTF8=1
./Runtime/venv/Scripts/python.exe -m pytest Harness/tests -q
./Runtime/venv/Scripts/python.exe scripts/verify_onboarding.py
powershell -NoProfile -ExecutionPolicy Bypass -File ./Harness/bin/printlab.ps1 doctor

# PrintLabInterface（在 E:\MyProjet\PrintLabInterface）
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m pip install -e ".[test]"

# 重启 PrintLab 工作台（在 E:\MyProjet\PrintLab）
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/start.ps1
```

---

## 9. 变更记录
- 2026-11-17：创建本文件。记录 PrintLab 初始化、H2C 接入、NarraFork 调研、方案 A/Python/P0 决策、P0-1 与 P0-2 完成状态。
- 2026-11-17：P0-3 Spike 完成（`docs/SPIKE_P0_3.md`、`docs/spike_p0_3.py`）。发现并复现环境变量白名单过窄会产生 `%SystemDrive%` 垃圾目录污染 PrintLab 的 git 状态；已清理，G1 恢复。P0-4 完成，G1–G4 通过，P0 收尾。
- 2026-11-17：P1 完成。新增 config、redact、db、app、`adapters/printlab/{policy,runner,http,adapter}`，90 个测试通过；实服务验证读取真实 PrintLab 且不改动其 git 状态；G1–G4 通过。依赖 litellm、langgraph 写入 `pyproject.toml`（带上限），尚无锁定文件。
