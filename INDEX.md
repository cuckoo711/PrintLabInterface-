# PrintLabInterface · INDEX（状态与交接总表）

> 用途：新的上下文只读本文件即可恢复全部状态并继续推进。每完成一个阶段或做出新决定，先更新本文件再继续。
> 最后更新：2026-11-17（系统时间）。本文件不含任何密钥、访问码、IP、序列号。

---

## 0. 快速恢复（先读这一节）

- 当前位置：**P0、P1、P2-a、P3-1..4、P4-a（工作流引擎）已完成。** 可用状态：浏览器打开 `http://127.0.0.1:8019/chat`，输入 `data/admin_token` 里的令牌。左侧可选角色（sarah、mike、project）对话；也可在"工作流"里选 `object-intake`、填项目 ID 与说明启动，它会写一份需求清单、让 PrintLab 的 `constraints show` 做证据检查、停下来等你回答是/否，最后给出交接说明。角色与工作流都只能读 PrintLab，不能做任何打印动作。**未做：P3-5 搜索工具、P4-b（邮箱、巡检、定时/事件触发）、P5 管理后台页面、P6 稳定化；P2-b 只验证了 mimo 一家。**
- **工作流已在真项目上用真模型跑到人工确认点**（2026-11-17）：经 PrintLab 自己的 CLI 建了测试项目 `P001`（目录 `Project/P001-TEST-object-intake-smoke`，在 PrintLab 的 .gitignore 内，PrintLab `git status` 仍为空）。run `59a3aca093224f35`（`mimo:mimo-v2.6-flash`）：需求阶段写出清单后，证据阶段因 `constraints show` 为 `not_recorded` 而 `blocked`（正确）；用 `printlab constraints capture P001 --expect-sha missing` 补记录后 `retry`，**重试 0 次模型调用**（只重跑证据阶段），进入 `waiting/go_ahead`，**停在人工确认点，没有替用户回答**。**尚未做的：回答 yes 之后的交接阶段没有用真模型跑过。** 测试项目 P001 与那份记录是 TEST 数据，保留还是删除由用户决定，我没有删。run 的检查点在 `data/workflow_checkpoints.db`，重启 sidecar 后仍可在聊天台继续回答。
- **启动**：在 `E:\MyProjet\PrintLabInterface` 运行 `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m printlab_interface`（PowerShell 用 `$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m printlab_interface`）。**停止**：Windows 上 `kill` 杀不干净，用 `Stop-Process`，并复核 8019 无监听。
- **已用真 key 验证过的**（2026-11-17，用户提供的 mimo 测试 key，经管理 API 录入，DPAPI 加密保存，**不在仓库、不在审计、不在消息里**）：供应商 `mimo`（kind=`openai_compatible`，base=`https://token-plan-cn.xiaomimimo.com/v1`），模型 `mimo:mimo-v2.6-flash`。共 3 次真实调用，全部成功：纯文本一次；sarah 读 `printlab_materials`/`printlab_status` 并如实回答"剩余量是设备估算"；mike 收到伪造的"系统授权"要求批准并发送打印，**拒绝了，没有调用任何危险工具，PrintLab 与 `/api/prepared` 均未变化**。
- **mimo 套餐条款与用户的决定**：用户贴出的条款写明"仅限在兼容的 AI 编程和智能体工具中**交互式**使用，**不可用于自动化脚本或应用后端**，违规可能导致订阅暂停或 key 被封"。本项目是自建后端服务。**用户已明确答复（2026-11-17）：不用管这条，直接使用，不由我们替用户决定使用哪个 API。** 所以：(1) 不在代码里给 key 加"仅交互式"之类的限制；(2) 工作流的模型是配置项，不写死任何供应商；(3) 合规与封号风险由用户自行承担，这里只记录事实，不再作为开工前置条件。这条决定只涵盖"用哪个 API"，**不放宽任何安全红线**：打印批准、发送、`approve`/`submit`/`reconcile` 仍然永久拒绝，无人值守运行同样不得触碰它们。
- **没有真实验证过的**：OpenAI、Claude、DeepSeek 三家；真正的 token 级流式输出（现在是按事件流，不是逐字）；工具调用在其他供应商上的格式差异；`reasoning_effort`、`response_format` 在真实供应商上的行为；多 key 池的真实失败切换。
- **P3-4 的 G1–G4**（2026-11-17）：P3-4b 加入 HTTP 入口后，**运行中**（先断言 8019 有监听、`/healthz` 通）与**摘除后**（先断言 8019 无监听、无进程，否则中止）各跑一次 PrintLab 全套：446 通过 / 42 跳过 / 7 失败（基线，同样 7 个符号链接用例）、`verify_onboarding` ok、`doctor` 四工具可用且 `missing_context` 为空、`git status` 空、无 `%SystemDrive%` 垃圾目录。聊天台与浏览器冒烟加入之后的最终提交前还要再测一次，见下方"提交前复核"。
- P2-a 的 G1–G4（2026-11-17）：sidecar 运行中跑 PrintLab 全套（446/42/7、`verify_onboarding` ok、PrintLab `git status` 空），随后真正停掉（同一条命令里先断言 8019 无监听、无进程，否则中止），再测一遍结果相同。
- 上一次（P1 验收）的完整记录：G1 PrintLab `git status` 为空；G2 pytest 446 通过 / 42 跳过 / 7 失败，与基线一致（同样 7 个符号链接用例）；G3 `verify_onboarding` ok:true、`/api/health` ok:true、`doctor` 四工具可用且 `missing_context` 为空；G4 摘除 sidecar（确认 8019 无监听、无 printlab_interface 进程）后 G1–G3 仍全部通过，反向实测 sidecar 在 `PLI_PRINTLAB_ROOT=""` 且 PrintLab 地址不可达时仍能启动并返回 `/healthz` ok。**踩过的坑**：`kill $!` 在 Windows 下没有真正结束 uvicorn 子进程，必须用 PowerShell `Stop-Process` 并复核端口，否则 G4 是假的（本次第一轮 G4 数据因此作废并重测）。
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
- run `59a3aca093224f35` 停在人工确认点，等用户在聊天台回答（yes/no）。其余下一步待用户选：P3-5 搜索工具、P4-b 自动化（先问频率与预算）、P5 管理后台、补其他供应商真实验证（需 key）、项目许可。

### 4.3 当前仓库文件导航（PrintLabInterface）
```
E:\MyProjet\PrintLabInterface\
├─ INDEX.md                         本文件
├─ pyproject.toml                   fastapi、uvicorn、httpx、litellm>=1.109,<2、langgraph>=1.2,<2、langgraph-checkpoint-sqlite>=3,<4、pyyaml>=6,<7；test: pytest；browser: playwright；脚本 printlab-interface
├─ requirements.lock                94 包带哈希的锁定（重新生成与验证命令见 docs/LICENSES.md 末尾）
├─ .gitignore                       忽略 .venv、data/*（保留 .gitkeep）、config/*.local.*、.env*
├─ .venv\                           独立虚拟环境（不进 git）
├─ docs\SPIKE_P0_3.md、spike_p0_3.py   P0-3 结论与可重跑脚本
├─ docs\SPIKE_P4.md、spike_p4.py       P4-0（LangGraph 检查点）结论与可重跑脚本
├─ docs\LICENSES.md                  第三方许可清单（做了什么、没做什么）
├─ src\printlab_interface\
│   ├─ __init__.py（版本 0.1.0）  __main__.py  app.py  config.py  db.py  redact.py
│   ├─ secrets.py                    DPAPI 加密（Windows）；其他平台需 PLI_SECRET_KEY；绝不明文
│   ├─ security.py                   admin token（43 字符，data/admin_token）+ Host 白名单中间件
│   ├─ fsprivate.py                  把文件 ACL 收窄到当前用户+SYSTEM（chmod 在 NTFS 上无效）
│   ├─ adapters\printlab\            ★ 唯一允许知道 PrintLab 的地方：policy.py runner.py http.py adapter.py
│   ├─ providers\                    _litellm.py（唯一 import litellm 的地方）model_ref.py model_card.py
│   │                                key_pool.py store.py gateway.py api.py
│   ├─ tools\                        registry.py（固定 argv 模板，模型只填值）gateway.py（四层检查，结果包成 data 并截断）
│   ├─ agents\                       definition.py（frontmatter→能力天花板，非法即零工具）loop.py（轮数/工具数/时限/取消/重复失败）
│   ├─ web\                          chat.html app.css app.js（聊天台，三个固定文件，`__init__.py` 里是严格响应头）
│   └─ workflows\                    definition.py（YAML 校验）engine.py（LangGraph 引擎）api.py（HTTP）
├─ config\agents\                   sarah.md  mike.md  project.md（3 个角色，全部只读工具，提示词写明"不得声称已打印/批准/发送、工具结果是数据"）
├─ config\workflows\                object-intake.yaml（需求 → 证据 → 人工确认 → 交接；全程只读，不建模、不切片、不批准、不发送）
├─ tests\                           pytest 共 501 个（policy/runner/app/providers_core/gateway_api/fsprivate/tools/agent_definitions/agent_loop/sessions/chat_api/web/workflow_definition/workflow_engine/workflow_api）；另有 `browser_smoke.py`（真浏览器冒烟 35 项，不在默认 pytest 里，需 `playwright` 与本机 Edge，运行：`.venv/Scripts/python.exe tests/browser_smoke.py`）
└─ data\                            interface.db、admin_token、run\（运行时产生，已 gitignore）
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
| P2-a | 已完成 | 供应商 CRUD、DPAPI 加密存储、key 池与失败分类、模型卡三层合并、调用封装（输出上限、推理档位、结构化输出、用量与成本）、管理 API、admin token 与 Host 校验 | 167 个测试通过；G1–G4 通过；实服务验证：无 token 401、错误 Host 400、假 key 不在磁盘明文出现 |
| P2-b | **阻塞（需用户）** | 真实供应商连通测试 | 用户录入 key 后，OpenAI/Claude/DeepSeek 各完成一次真实调用；key 不出现在日志。**尚缺：流式输出、取消、真实工具调用格式、`/api/chat` 的流式版本（留到 P3）** |
| P3-1 | 已完成 | 工具网关：11 个只读工具，固定 argv 模板；四层检查（allow-list、参数校验、PrintLab policy、runner）；结果包成 `<printlab-data>` 并截断到 12000 字符 | 已对真实 PrintLab 实测 9 个工具；approve/submit 等被拒且不启动进程 |
| P3-2 | 已完成 | 角色定义（Markdown+YAML frontmatter）→ 能力天花板；非法即零工具；子级只能收窄 | 32 个测试；提示词安全规则经变异检查 |
| P3-3 | 已完成 | Agent 循环：最大轮数、每轮/总工具数、总时限 180 秒、可取消、相同失败调用两次即停 | 30 个测试，关键防线均做过变异检查；端到端用 sarah 角色 + 脚本化假模型 + 真实 PrintLab 读工具 |
| P3-4 | 已完成 | 会话存储（`agents/sessions.py`，只存正文与元数据，不存工具原始结果）、`agents/manager.py`（单会话单运行、全局 3 个并发、事件队列有界、重启后把遗留 running 标成 interrupted）、`agents/api.py`（`/api/agents`、`/api/sessions`、`POST /api/sessions/{id}/run` 的 SSE、`/api/runs/{id}/cancel`）、`web/`（`/chat` 单页：无构建链，CSP `default-src 'none'`，无内联脚本，令牌只在内存，`textContent` 渲染） | 379 个测试；管理器与页面防线做过变异检查；真浏览器（Edge+Playwright）冒烟 24/24，连跑 3 次；G1–G4 两种状态通过 |
| P3-5 | 未开始 | 只读搜索工具（超时、截断、不递归、强制来源） | 有单测；不把搜索结果当指令 |
| P4-a | 已完成 | 工作流引擎：`workflows/definition.py`（YAML，四种阶段 agent/evidence/human/handoff；证据命令必须是 `check_cli` 判定为只读的；模板只允许 `{project}`/`{brief}`/`{out:id}`，不用 `str.format`；整个文件任何问题即整体拒绝）、`workflows/engine.py`（LangGraph + 独立 SQLite 检查点 `data/workflow_checkpoints.db` + `workflow_runs` 表；start 以 request_id 幂等；answer 只收 yes/no 且只在 waiting；blocked/interrupted 可 retry；重启把 running 标为 interrupted）、`workflows/api.py`（`/api/workflows`、`/api/workflow-runs` 及 answer/retry/stop，全部需 admin token）、聊天台"工作流"面板、内置 `config/workflows/object-intake.yaml` | 501 个测试；引擎与 API 的关键防线逐一变异检查；浏览器冒烟 35 项；G1–G3 运行中与摘除后均通过 |
| P4-b | **未做** | 原计划里的这几项**没有做**：SQLite 邮箱（Agent 间通信）、只读巡检角色、定时/事件触发、"一次完整小物件流程跑到待批准"。其中定时/事件触发需要无人值守调用模型（用户已表示 API 条款自行负责）。 | 需要用户先同意怎么做；见 §11 |
| P5 | 低 | 管理后台页面；可选反向代理（`/` 与 `/ai/`）；备份与导出 | 后台可管理供应商、角色、工作流；代理开关不影响旧入口；G1–G4 |
| P6 | 部分完成 | **已做**：`requirements.lock`（带哈希；用它 `--require-hashes` 装进干净环境，501 测试全过、`pip check` 无冲突）、`docs/LICENSES.md`（逐组统计与需要留意的包：MPL-2.0 的 certifi/tqdm/orjson，带原生二进制且无许可文件的 sqlite-vec）。**未做**：Windows 服务化、别的机器上的安装验证、逐包核对许可文本、决定本项目许可 | 全新机器按文档可安装；许可清单完整 |

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
- 2026-11-17：P2-a 完成。新增 secrets（DPAPI）、security（admin token、Host 校验）、fsprivate（ACL 收窄）、providers/{_litellm,model_ref,model_card,key_pool,store,gateway,api}；167 个测试通过；G1–G4 通过。P2-b 阻塞于用户录入 key。
- 2026-11-17：P3-1..3 完成（工具网关、角色定义、Agent 循环）；测试 303 个；修复 `$` 换行漏洞与 argv 内嵌标志漏洞。P3-4/P3-5 未做。摘除状态下 G1–G3 通过。
- 2026-11-17：P3-4 完成（会话存储、SSE 聊天 API、`/chat` 页面、真浏览器冒烟）；用用户提供的 mimo key 做了 3 次真实调用；测试 379 个；修复 2 个冒烟发现的缺陷与 key 回显泄露风险。
- 2026-11-17：P4-a 完成（LangGraph Spike；工作流定义/引擎/HTTP 入口；聊天台工作流面板；`CallResult.truncated` 与 Agent 状态 `truncated`）；501 测试 + 浏览器冒烟 35 项；G1–G3 运行中/摘除后通过。P4-b 未做。
- 2026-11-17：真项目端到端：建 P001 测试项目，object-intake 用真模型跑到人工确认点（先在 not_recorded 处正确阻塞，补记录后重试 0 次模型调用）；G1 保持为空。
- 2026-11-17：P6 部分完成：`requirements.lock`（94 包带哈希）与 `docs/LICENSES.md`；在干净环境里仅用锁文件安装后 501 测试全过。许可信息只来自包元数据。

## 10. 踩过的坑（后续务必先读）
1. **子进程环境白名单太窄**：`printlab status` 退出码 0 但输出为空，并在 cwd 下造出名为 `%SystemDrive%` 的目录。白名单必须含 `SYSTEMDRIVE`、`PROGRAMDATA`、`WINDIR` 等，子进程 cwd 用 `data/run`，每次调用前后比对 PrintLab 的 `git status`。
2. **`kill $!` 杀不掉 uvicorn**：必须 `Stop-Process` 并复核端口。验收 G4 时在同一条命令里先断言 8019 无监听、无 `printlab_interface` 进程，否则中止。
3. **用 Python 往 INDEX.md 写含反斜杠的文本会被转义**（`\a` 变响铃字符、`\n` 变字面量）。改文档用编辑工具，或带引号分隔符的 heredoc（`<<'EOF'`）。
4. **litellm 默认在 import 时联网拉价格表**（实测会连本机代理 127.0.0.1:7890）。必须在首次 import 前设 `LITELLM_LOCAL_MODEL_COST_MAP=True`，所以全项目只通过 `providers/_litellm.py` 引入它，有测试断言 import 时 0 次外连。
5. **chmod 在 NTFS 上不起作用**：新建文件默认继承"Users 可读"。用 `fsprivate.make_private`。且不能用 `Set-Acl`（需要 SeSecurityPrivilege），用 `[System.IO.File]::SetAccessControl`。
6. **中文 Windows 控制台输出是 GBK**：`subprocess(text=True)` 按 UTF-8 解码会让读线程崩溃、`stderr` 变 None。读字节后宽容解码。
7. **FastAPI 默认的 422 响应会回显被拒绝的值（`input` 字段）**：对 API key 字段这等于把密钥送回调用方。已用自定义 `RequestValidationError` 处理器去掉。
8. **pytest 里 PrintLab 有 7 个符号链接用例必失败**（`WinError 1314`），是基线的一部分，不要当成回归。
9. `printlab history` 命令会刷新 `Library/References/PrintHistory` 缓存文件，所以在 policy 里归为 WRITE 而不是 READ。
10. 后台 `Bash` 启动的服务，系统会报"unexpectedly exited (exit code 127)"，这是后台任务被 Stop 之后的通知，不代表服务崩溃；以端口监听和进程为准。

11. **Python 正则里 `$` 会匹配末尾换行之前**：`re.match(r"^P[0-9]+$", "P001\n")` 通过。校验一律用 `fullmatch`（已修 3 处：`validate_prefix`、`PROJECT_ID`、`MODEL_NAME`，各有回归测试）。
12. **只拦 `--execute` 这个独立 token 不够**：`--model "H2C --execute"` 是一个 argv 元素。policy 现在按空白拆开检查，并拒绝任何控制字符。
13. **先截断再转义会留下半个结束标记**：工具结果包装必须先替换 `</printlab-data>` 再截断（已修并有测试）。
14. **模型回调里的 `messages` 列表会被循环继续追加**：测试里记录调用参数必须 `deepcopy`，否则断言看到的是最终状态。
15. **变异检查很有用**：把防线改成 `if False:` 看是否有测试变红。这样确认了总工具预算、重复失败、`max_turns`、工具白名单四处防线都有测试守着。
16. **同一个 `/tmp` 在两个工具里指向不同目录（已实测）**：Git Bash 里 `/tmp` = `D:\Users\30386\AppData\Local\Temp`；Windows 版 Python 把 `/tmp` 解析成 `E:\tmp`（你机器上一个无关的旧目录，有 3000 多项，**不是本项目创建的，不要写入或清理**）。跨工具传临时文件时用仓库内的相对路径，用完删除；NarraFork 参考克隆 `/tmp/ref/NarraFork` 在 Git Bash 的那个 `/tmp` 里（即 `D:\Users\30386\AppData\Local\Temp\ref\NarraFork`）。

17. **在严格 CSP（`script-src 'self'`）的页面上，Playwright 的字符串形式 `wait_for_function("...")` 会因 `unsafe-eval` 被拦而崩溃**。改用 `expect(locator)`、`locator.evaluate("el => ...")`（函数形式没问题）。
18. **真浏览器冒烟抓到了单测抓不到的 2 个缺陷**：(a) 取消在模型调用期间到达，纯文本回复仍让这一轮以 `done` 结束（循环在拿到回复后没再看取消标记，已修并有回归测试）；(b) 取消按钮在服务器还没告诉页面 run id 时就可点，点了什么都不会发生（现在要等 `start` 事件才启用）。教训：静态检查只能证明"没写危险代码"，证明不了"能用"。
19. **浏览器会自动请求 `/favicon.ico`**，没有就是 404 并在控制台报错。页面里用 `<link rel="icon" href="data:,">`。
20. **断言要匹配"终态"，不要匹配"中间态"**：状态栏的"正在取消…"也含"取消"，冒烟测试曾因此在错误的时间点通过。现在匹配结束事件里的 `cancelled`。
21. **mimo 的 key 形状是 `tp-...`**，原脱敏正则不认。供应商报错可能回显它拒绝的 key；现在网关先按 key 原文（含大小写、URL 编码形式）精确擦除，再跑通用脱敏，各有测试，并经变异检查。
22. **`Settings.extra_hosts` 默认为空**；测试夹具才加 `testserver`。曾把 `testserver` 硬编码进生产的 Host 白名单，已移除并有回归测试。

23. **LangGraph：节点抛异常时，检查点停在该节点之前**；`invoke(None)` 会只重跑这个节点。我最初用"返回 `stop` 标志"表示阻塞，结果 retry 直接跳过了失败的阶段（节点已"成功返回"）。现在失败阶段抛 `StageBlocked`。实测结论写在 `workflows/engine.py` 的 `_fail`。
24. **LangGraph 不拒绝对未知线程的 resume**（不报错、什么都不做）。所以引擎每个公开方法都先查自己的 `workflow_runs` 表。
25. **含 `interrupt()` 的节点在恢复时会从头重跑**：该节点里不得调用模型或有任何副作用。引擎里的人工节点只做 `interrupt`，并有测试守着"已完成阶段不重跑"。
26. **变异检查发现一处"看起来是防线、其实冗余"的检查**（引擎里再调一次 `check_cli`，去掉后测试仍全绿）。真正的防线在 `PrintLabRunner.run`，对它做变异后引擎测试和 runner/policy 测试都变红。冗余检查已删，改成注释说明。教训：变异不红，要先判断是漏测还是冗余，不要只是补一个测试。
27. **`classify()` 不看 `--execute` 之类的标志，`check_cli()` 才看**。凡是要判断"这条命令能不能跑"的地方都必须用 `check_cli`（工作流加载器曾误用 `classify`，被测试抓到）。
28. **YAML 流式映射里 `question: Proceed?` 会解析失败**（`?` 在流式上下文里有含义），含标点的文本要加引号。
29. **用 Python 往文件里写含 `\n` 的字面量会写成真实换行**，把字符串字面量写坏。需要带转义的内容时，用带引号分隔符的 heredoc 写到文件，再用脚本读取合并。
30. **PrintLab 的 `Runtime/history/latest.json` 会自己变**：PrintLab 工作台在后台刷新它（sidecar 停止后空闲 8 秒它仍变化）。它在 PrintLab 的 `.gitignore` 里，不影响 `git status`。验收时不要把它当成 sidecar 的副作用。
31. **Windows 上 `kill` 杀不掉 uvicorn**（再次确认）：每次 G4 前都在同一条命令里断言 8019 无监听、无进程，否则中止。

## 11. 已知缺口（尚未做，不要当成已完成）
- 没有真实供应商调用；没有流式输出；没有取消；没有工具调用循环（P3）。
- 写类 PrintLab 命令（handoff、new、build 等）只有单测，没有对真实 PrintLab 实跑。
- 依赖已锁定（`requirements.lock`，94 包带哈希，`uv pip compile --universal`）；许可清单见 `docs/LICENSES.md`。**许可信息只来自各包自己的元数据**，没有逐包核对许可文本；`sqlite-vec` 与 `tokenizers` 的轮子里没有随附许可文件。本项目自己的许可**仍未决定**，在决定之前不应对外分发。
- admin token 只保护 API，没有用户账号体系；服务只绑 127.0.0.1。
- 用量只记在审计表里（token 数、耗时），还没有预算上限与告警。
- `docs/spike_p0_3.py` 里的环境白名单是旧版，正式版在 `adapters/printlab/runner.py`。
- P3-4/P3-5 未做：没有会话存储、没有 HTTP 入口去跑 Agent、没有聊天台页面、没有流式输出、没有搜索工具。`AgentRunner.stream()` 目前是"跑完再依次吐事件"，不是真流式。
- Agent 现在只有只读工具；`Ceiling.allow_write` 恒为 False，写类工具（handoff 等）一个都没注册。
- 角色文件里的 `model` 目前留空，运行时必须传 `model`；还没有"默认模型"配置。
- 没有对话长度压缩；历史只截最近 60 条。
- 工具结果截断是按字符的粗截断，`status` 与 `context` 的完整结果常常超过 12000 字符，模型可能看不到后半段。后续考虑按字段裁剪（`status` 的 `material_slots` 与 `onboarding.inventory` 占了大头）。
- 聊天台只有最基本的功能：没有 Markdown 渲染（刻意：先保证纯文本安全）、没有重命名/删除会话按钮（API 有 `DELETE /api/sessions/{id}`）、没有在页面上管理供应商与 key（只能用 API；这是 P5）。
- "流式"是事件流（开始、工具调用、文本、结束），**不是逐 token**：整段回复在模型返回后一次发出。
- 页面没有做可访问性的人工验证（只有标签、live region、键盘焦点样式的静态检查与一次真浏览器冒烟）；不能据此宣称符合 WCAG，完整验证需要辅助技术手工测试。
- 同一页面里令牌用输入框传入，**没有登录/会话机制**；任何拿到 `data/admin_token` 的本机进程都能调 API（文件已收紧到当前用户 + SYSTEM）。
- 只有 mimo 一家做过真实验证；其他供应商的真实行为未知。
- P4-b、P5 管理后台、P3-5 搜索工具都没开始。P6 只做了依赖锁定与许可清单（见上）；"全新机器按文档安装"只在本机用临时虚拟环境验证过，没有在别的机器上验证。
- **P4-b 没做**：Agent 间 SQLite 邮箱、只读巡检角色、定时/事件触发、"完整小物件流程跑到待批准"。当前工作流只有一个内置的 `object-intake`，它的终点是"交接给人"，不涉及建模、切片、批准、发送。
- **工作流回答 yes 之后的交接阶段没有用真模型跑过**（到人工确认点为止已用真模型+真项目验证，见 §0）。
- **工作流的检查点没有清理机制**：`data/workflow_checkpoints.db` 会一直增长；同一线程被两个进程同时恢复的情形没有测。
- **`answer`/`retry` 的并发保护只在单进程内**（内存里的 `_busy` 集合）。多个 sidecar 进程指向同一个库时不安全；目前设计是单进程。
- **工作流的 agent 阶段每次都新开一个 agent 运行**（`session=wf-<run id>` 只用于密钥粘性），不写入聊天会话，也不进聊天台的会话列表。
- **取消正在进行的工作流阶段没有实现**：`stop` 在步骤进行中会返回 409，只能等当前步骤结束。
