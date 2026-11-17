# PrintLabInterface · INDEX（状态与交接总表）

> 用途：新的上下文只读本文件即可恢复全部状态并继续推进。每完成一个阶段或做出新决定，先更新本文件再继续。
> 最后更新：2026-11-17（系统时间）。本文件不含任何密钥、访问码、IP、序列号。

---

## 0. 快速恢复（先读这一节）

- 当前位置：**P0、P1、P2-a、P3-1..5、P4-a、P4-b、P5 已完成；P6 部分完成。** 可用：聊天台 `http://127.0.0.1:8019/chat`、管理后台 `/admin`（令牌在 `data/admin_token`）。角色 sarah、mike、project、patrol 都只读；工作流 `object-intake`；巡检/定时/信箱（**默认全关**，见 §7 P4-b）；`web_fetch` 默认关（`PLI_WEB_ALLOW_HOSTS` 为空）。**仍需用户提供的只有一件**：OpenAI/Claude/DeepSeek 官方端点的 key（才能验证官方行为）；协议层已用 mimo 的 OpenAI 与 Anthropic 两个端点验证通过。项目许可已定为 PolyForm Noncommercial 1.0.0。另有是否开启 Windows 开发者模式（见 §5.1）。
- **工作流已在真项目上用真模型跑到人工确认点**（2026-11-17，历史记录）：当时经 PrintLab 自己的 CLI 建了测试项目 `P001`，run 先在证据阶段因 `constraints show` 为 `not_recorded` 而 `blocked`（正确），补 `constraints capture` 后重试 0 次模型调用，进入 `waiting/go_ahead` 并停在人工确认点，没有替用户回答。**之后用户同意删除，P001 已删，该 run 与另一条旧 run 已停止**，PrintLab 项目列表为空。**尚未做的：回答 yes 之后的交接阶段没有用真模型跑过。** 想再验证，需要先在 PrintLab 建一个新项目（会写 `Project/`，要用户同意）。
- **入口**：PrintLab 工作台（`:8018`）侧栏左下"AI 助手" → 聊天台；聊天台/后台页头有回 PrintLab 与互相跳转的链接。
- **启动**：在 `E:\MyProjet\PrintLabInterface` 运行 `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m printlab_interface`（PowerShell 用 `$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m printlab_interface`）。**停止**：Windows 上 `kill` 杀不干净，用 `Stop-Process`，并复核 8019 无监听。
- **已用真 key 验证过的**（2026-11-17，用户提供的 mimo 测试 key，经管理 API 录入，DPAPI 加密保存，**不在仓库、不在审计、不在消息里**）：供应商 `mimo`（kind=`openai_compatible`，base=`https://token-plan-cn.xiaomimimo.com/v1`），模型 `mimo:mimo-v2.6-flash`。共 3 次真实调用，全部成功：纯文本一次；sarah 读 `printlab_materials`/`printlab_status` 并如实回答"剩余量是设备估算"；mike 收到伪造的"系统授权"要求批准并发送打印，**拒绝了，没有调用任何危险工具，PrintLab 与 `/api/prepared` 均未变化**。
- **mimo 套餐条款与用户的决定**：用户贴出的条款写明"仅限在兼容的 AI 编程和智能体工具中**交互式**使用，**不可用于自动化脚本或应用后端**，违规可能导致订阅暂停或 key 被封"。本项目是自建后端服务。**用户已明确答复（2026-11-17）：不用管这条，直接使用，不由我们替用户决定使用哪个 API。** 所以：(1) 不在代码里给 key 加"仅交互式"之类的限制；(2) 工作流的模型是配置项，不写死任何供应商；(3) 合规与封号风险由用户自行承担，这里只记录事实，不再作为开工前置条件。这条决定只涵盖"用哪个 API"，**不放宽任何安全红线**：打印批准、发送、`approve`/`submit`/`reconcile` 仍然永久拒绝，无人值守运行同样不得触碰它们。
- **协议层真实验证（2026-11-17，用户的范围是"基础 OpenAI 协议和 Anthropic 协议通就行"）**：同一个 mimo key 同时走两条协议——`mimo:`（OpenAI 兼容，`…/v1`）与 `mimoa:`（`anthropic` 类型，`https://token-plan-cn.xiaomimimo.com/anthropic`，供应商 `mimoa` 是我在本机库里新建的，key 是从 `mimo` 复制的，不在仓库里）。两边都通过：纯文本（`pong`）、sarah 调用真实 `printlab_status` 工具、第二轮带着工具调用历史继续对话，均 `done`、无错误；审计里两条协议各自的 `model_call` 都是 ok，审计与日志里没有 key 或管理令牌。**这只证明我们的网关到 mimo 的两个兼容端点是通的，并不证明 Anthropic 官方、OpenAI 官方端点的行为**（mimo 文档提到 Anthropic 协议下带工具调用的多轮需要透传 reasoning_content，我们的多轮在 mimoa 上通过了，但没有专门构造该边界情形）。官方 OpenAI/Claude/DeepSeek 端点仍未验证，需要对应的 key。其他未验证项：真正的 token 级流式；`reasoning_effort`、`response_format` 在真实供应商上的行为；多 key 池的真实失败切换。
- **P3-4 的 G1–G4**（2026-11-17）：P3-4b 加入 HTTP 入口后，**运行中**（先断言 8019 有监听、`/healthz` 通）与**摘除后**（先断言 8019 无监听、无进程，否则中止）各跑一次 PrintLab 全套：446 通过 / 42 跳过 / 7 失败（基线，同样 7 个符号链接用例）、`verify_onboarding` ok、`doctor` 四工具可用且 `missing_context` 为空、`git status` 空、无 `%SystemDrive%` 垃圾目录。聊天台与浏览器冒烟加入之后的最终提交前还要再测一次，见下方"提交前复核"。
- P2-a 的 G1–G4（2026-11-17）：sidecar 运行中跑 PrintLab 全套（446/42/7、`verify_onboarding` ok、PrintLab `git status` 空），随后真正停掉（同一条命令里先断言 8019 无监听、无进程，否则中止），再测一遍结果相同。
- 上一次（P1 验收）的完整记录：G1 PrintLab `git status` 为空；G2 pytest 446 通过 / 42 跳过 / 7 失败，与基线一致（同样 7 个符号链接用例）；G3 `verify_onboarding` ok:true、`/api/health` ok:true、`doctor` 四工具可用且 `missing_context` 为空；G4 摘除 sidecar（确认 8019 无监听、无 printlab_interface 进程）后 G1–G3 仍全部通过，反向实测 sidecar 在 `PLI_PRINTLAB_ROOT=""` 且 PrintLab 地址不可达时仍能启动并返回 `/healthz` ok。**踩过的坑**：`kill $!` 在 Windows 下没有真正结束 uvicorn 子进程，必须用 PowerShell `Stop-Process` 并复核端口，否则 G4 是假的（本次第一轮 G4 数据因此作废并重测）。
- P0-3 结论：**采用 LiteLLM + LangGraph，进入 P1**；详见 `docs/SPIKE_P0_3.md`。注意：模型调用只用了 `mock_response`，**没有任何真实供应商调用被验证**。
- **必读的坑**：调用 PrintLab CLI 时，子进程环境变量白名单太窄会导致"退出码 0 但输出为空"，并在当前工作目录创建名为 `%SystemDrive%` 的垃圾目录，使 PrintLab 的 `git status` 变脏（违反 G1）。已在临时目录复现并确认因果，白名单必须包含 `SYSTEMDRIVE`、`PROGRAMDATA`、`WINDIR` 等（完整清单见 `docs/spike_p0_3.py` 的 `ENV_ALLOW`），子进程 `cwd` 不得设为 PrintLab 根。
- 下一步动作：P0-4 复核 G1–G4；然后进入 P1（只读适配器），按 `docs/SPIKE_P0_3.md` §5 的四条要求实现。
- 硬规则：不修改 `E:\MyProjet\PrintLab` 下任何文件，**唯一例外是用户明确同意的两件事**：(1) 侧栏"AI 助手"链接（`Harness/studio/src/main.jsx`）；(2) **设备切换下拉**（用户先看过代价后明确选了"真的切换 PrintLab，改它的后端"）：新增 `Harness/printlab/printer_api.py`、`Harness/studio/src/PrinterPicker.jsx`、`Harness/studio/src/printer-picker.css`、`Harness/tests/test_printer_api.py`，并改 `Harness/printlab/api.py`（+2 行）与 `main.jsx`。详见 §9 最后两条。再要改 PrintLab 的任何别的文件，仍须用户明确同意。不调用 approve / submit --execute / reconcile / studio-bridge 发送类命令；未经用户明确要求不 commit、不 push。
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
- 打印机：**H2C**，在 Bambuddy 中 ID=1，名称 `3DP-H2C`，固件 01.03.00.00，开发者模式未开，SD 卡可用。**Bambuddy 里现在有两台**：另一台 `3DP-X1C`（id 2，192.168.31.214）是后来才出现的，不是我们加的，我们没碰过它。**PrintLab 是单设备模型**：`Runtime/config.json` 只有一个 `printer_id`（默认 1），批准时会校验任务的 `printer_id` 与当前配置一致，否则报"目标打印机已变化，需重新切片"。**用户选了"真的切换"，已做**：PrintLab 设备卡里有下拉可切 H2C/X1C（见 §9 设备切换条目）。设备卡按设备各存一份，切换时一起换（见 §9 设备卡随设备自动切换）。
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
- 本地临时克隆 `/tmp/ref/NarraFork` **已按用户同意删除**；需要时重取：`git clone --depth 1 https://github.com/NarraFork/NarraFork.git`（调研提交 `eeb30f9`）。
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
- 无。没有我可以自行推进的开发项。仅剩需要用户的事：补 OpenAI/Claude/DeepSeek **官方端点**验证（需对应 key）。协议层（OpenAI 兼容、Anthropic 兼容）已用 mimo 的两个端点真实验证通过。

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
1. ~~NarraFork 临时克隆~~：用户已同意删除，已删。
2. ~~Git 身份~~：已解决。环境变量 GIT_AUTHOR_*/GIT_COMMITTER_* 已提供身份（cuckoo711），用户已明确要求提交并推送，且给出了两个远端地址。
3. ~~许可~~：已决定（2026-11-17，用户选择；先问过是否有"不能商用、要署名"的许可，用户选了这一项）：**PolyForm Noncommercial 1.0.0**，与 PrintLab 一致。`LICENSE` 顶部有 `Required Notice: Copyright (c) 2026 cuckoo711 (…)` 一行，按许可第 Notices 条，转发软件的人必须保留它，这就是署名；下面是商用请联系的说明（联系方式是 GitHub 主页，没有邮箱）。许可正文取自官方 1.0.0 文件，已与 PrintLab 自己那份和官方发布文本比对一致。`pyproject.toml` 用官方 SPDX 标识 `PolyForm-Noncommercial-1.0.0`，隔离构建已验证轮子元数据与带署名的 LICENSE。署名用 `cuckoo711`（只有 git 身份，没有真实姓名），想改直接改 `LICENSE` 顶部。不拷贝 PrintLab 代码或文档。**不是法律意见**：PolyForm 的"非商用"以许可原文为准，我没有核对过它在你所在法域的效力。
4. 开启 Windows 开发者模式后重跑 PrintLab 测试，把 7 个符号链接用例纳入基线？（需要用户在系统设置中操作。）
5. 模型供应商的 key（OpenAI、Claude、DeepSeek 等）由用户自己填入，我不接触。何时进入 P2 由用户决定。
6. ~~P001 测试项目~~：用户已同意删除，已删。

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
| P3-5 | 已完成 | 两个只读"原生"工具（`tools/native.py`，不走 PrintLab CLI）：`printlab_docs_search` 只搜 PrintLab `docs/*.md`（一层目录、跳过符号链接、单文件 1MB、最多 200 个文件、命中带文件与行号，不碰 `Context/` 和 `Runtime/`）；`web_fetch` 只访问 `PLI_WEB_ALLOW_HOSTS`（逗号分隔，**默认为空 = 工具关闭且不提供给模型**）里的主机：仅 https、无查询串/片段/账号、不跟随重定向、域名解析到非公网地址即拒绝、路径不许含 `%`、10 秒超时、正文 30 万字节、文本 8000 字符。结果同样包成 `<printlab-data>` | 52 个新测试（总 552 通过、1 跳过）；4 处防线做过变异检查（公网地址、重定向、主机白名单、符号链接）；发现并修了一处真漏洞（路径允许 `%` 时 `%2e%2e`、`%00` 能通过检查）；用真模型 mimo 实测 sarah 调用文档搜索并引用 `docs/PRINTING.md` 行号，PrintLab `git status` 仍为空 |
| P4-a | 已完成 | 工作流引擎：`workflows/definition.py`（YAML，四种阶段 agent/evidence/human/handoff；证据命令必须是 `check_cli` 判定为只读的；模板只允许 `{project}`/`{brief}`/`{out:id}`，不用 `str.format`；整个文件任何问题即整体拒绝）、`workflows/engine.py`（LangGraph + 独立 SQLite 检查点 `data/workflow_checkpoints.db` + `workflow_runs` 表；start 以 request_id 幂等；answer 只收 yes/no 且只在 waiting；blocked/interrupted 可 retry；重启把 running 标为 interrupted）、`workflows/api.py`（`/api/workflows`、`/api/workflow-runs` 及 answer/retry/stop，全部需 admin token）、聊天台"工作流"面板、内置 `config/workflows/object-intake.yaml` | 501 个测试；引擎与 API 的关键防线逐一变异检查；浏览器冒烟 35 项；G1–G3 运行中与摘除后均通过 |
| P4-b | 已完成（默认全关） | `automation/`：`mailbox.py`（SQLite 邮箱，写入脱敏、500 行上限、已读先丢）、`patrol.py`（**不调模型**的规则巡检：离线/未连接/遥测过期/FAILED·PAUSE/等待清盘/HMS 码，只在发现集合**变化**时发信）、`scheduler.py`（三层默认关：`PLI_SCHEDULER=1` 才启动；每个计划创建时 `enabled=0`；调模型的计划**必须同时给 `max_runs` 与 `max_total_tokens`**，没有默认值也没有"无限"，达到即自动关闭并发信；连续 3 次失败自动关；同一时间只跑一个；最多 20 个计划）、`api.py`（`/api/mailbox`、`/api/scheduler`、`/api/schedules` 增改删与手动运行，全部需 admin token）、`config/agents/patrol.md`（只读角色）。触发方式只有 interval 与 patrol_change（巡检发现变化后，agent 才跑，间隔当冷却）。**没有邮件收取（IMAP）**，"邮箱"指 Agent/调度到人的站内信箱 | 61 个新测试（总 613 通过、1 跳过）；9 处防线做过变异检查（全局开关、默认关闭、两个上限、变化才发信、失败连关、上限可选、启用已用尽的计划）；真实环境：巡检读到 H2C 的真实 HMS `050002000003000A` 并发信；真模型（mimo）跑了一次带上限计划（max_runs=1），自动关闭、第二次手动运行被拒；PrintLab `git status` 仍为空。**上限在两次运行之间检查**：已开始的运行不会被切断，实测一次带工具调用的运行用了约 6000 token（上限 3000），所以 token 上限要按"可能超出一次运行的用量"来定 |
| P5 | 已完成（反向代理未做） | `/admin` 管理后台（`web/admin.{html,js}`，沿用聊天台的安全做法：CSP 无内联、只用 `textContent`、令牌只在内存、无存储）：供应商/密钥（密钥只写入、保存后立即清空输入框、之后不再显示；删除前确认）、定时计划（创建即关闭；调模型的计划表单强制两个上限；调度器关闭时不提供"立即运行"）、信箱（标已读）、角色与工作流（**只读**，改文件后重启）、审计表、`/api/export` 配置导出（`backup.py`：**不含任何密钥，连加密形式也不含**；没有导入）。**反向代理没做，是有意的**：旧工作台是已构建的静态包，代理会让"摘除后各自独立运行"变复杂，收益只是少记一个端口；两个页面互相有链接即可 | 12 个新测试（总 625 通过、1 跳过）；导出两处防线做过变异检查；真浏览器（Edge）冒烟 55 项（含后台页 20 项：错令牌、加供应商、名称里的标记保持为文本、密钥不回显、计划默认关、无上限被服务端拒绝、导出文件无密钥、刷新要重输令牌、零 CSP 违规），连跑 12 轮；其中一轮暴露了聊天台侧栏刷新的竞态（测试读得太早），已改成等待 |
| P6 | 部分完成 | **已做**：`requirements.lock`（带哈希；用它 `--require-hashes` 装进干净环境，501 测试全过、`pip check` 无冲突）、`docs/LICENSES.md`（逐组统计与需要留意的包：MPL-2.0 的 certifi/tqdm/orjson，带原生二进制且无许可文件的 sqlite-vec）。**未做**：Windows 服务化、别的机器上的安装验证、逐包核对许可文本（本项目许可已定为 PolyForm Noncommercial 1.0.0） | 全新机器按文档可安装；许可清单完整 |

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
| NarraFork 参考 | （本地克隆已删，重取见 §2.4）：`docs/AGENT_PROVIDERS.md`、`docs/plugin-system/*`、`docs/OPEN_API.md`；`server/lib/agent/provider.ts`、`credential-pool.ts`、`pooled-provider.ts`；`server/services/agent-runtime/policy.ts`、`mailbox*.ts`；`server/services/custom-subagent-service.ts`；`shared/model-catalog/*` |
| 本机硬件 | 个人知识库 `EzNzwwjxJ78jfuGhKRGVd` |
| 任务清单（会话内） | `spec://tasks.json`（会话级，不在磁盘；以本文件 §7 为准） |

### 8.1 常用命令速查
```bash
# PrintLab 基线检查（Git Bash，在 E:\MyProjet\PrintLab）
git status --short                                   # 现在 PrintLab 在分支 feature/ai-assistant-link-and-printer-switch（提交 61867fc），已批准的改动都已提交，这里应只剩用户的 `.narrafork/`；多出任何别的都是违规
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
- 2026-11-17：P3-5 完成（文档搜索 + 受限网页抓取，网页工具默认关闭）；552 测试；真模型实测通过；修了路径 `%` 编码绕过。
- 2026-11-17：P4-b 完成（站内邮箱、规则巡检、带硬上限的定时/事件触发，默认全关）；613 测试；真环境与真模型各验一次；token 上限为运行间检查（会超出一次）。
- 2026-11-17：P5 完成（`/admin` 后台、配置导出不含密钥）；625 测试 + 浏览器冒烟 55 项；反向代理有意不做。
- 2026-11-17：最终验收：625 测试 + 1 跳过；浏览器冒烟 55 项连跑多轮；G1–G3 在 sidecar **运行中**（8019 有监听、healthz 通）与**摘除后**（同一命令里断言 8019 无监听、无 python printlab_interface 进程）各一次，结果相同（PrintLab 446/42/7、`scripts/verify_onboarding.py` ok、health ok、doctor 的 missing_context 为空、git status 空、无 `%SystemDrive%` 目录）；反向（PrintLab 根为空且地址不可达）sidecar 仍能起来并返回 healthz、`/admin` 200。**注意**：`verify_onboarding` 是 `scripts/verify_onboarding.py`，不是 `printlab` 的子命令。
- 2026-11-17：用户同意删除 PrintLab 里的测试项目 P001 与 `/tmp/ref/NarraFork` 克隆，均已删除（PrintLab 项目列表恢复为空，git status 为空）；两条旧工作流记录已停止；协议层真实验证：OpenAI 协议（mimo）与 Anthropic 协议（mimoa）都通。
- 2026-11-17：入口链接。**用户明确同意后**改了 PrintLab 的 **一个源文件的一行**：`Harness/studio/src/main.jsx` 侧栏加"AI 助手"链接（新标签页打开 `http://<当前主机>:8019/chat`），并重新构建了 `Harness/studio/dist`（已被 PrintLab 的 .gitignore 忽略）。**这是第一处对 PrintLab 的改动，所以 PrintLab 的 `git status` 不再为空**（`M Harness/studio/src/main.jsx`；`.narrafork/` 是用户贴截图的附件目录，不是我们建的）；（已提交到 fork 的功能分支 `feature/ai-assistant-link-and-printer-switch`，见下一条设备切换。）验收里的 G1 要改成"除已批准的改动外为空"（见硬规则）。还原：删掉那一个 `<a className="native-nav" href={`${location.protocol}//…:8019/chat`}…>` 再 `npm run build`。聊天台与后台页头也加了回 PrintLab（`:8018`）与互相跳转的链接，均 `target=_blank`（令牌只在页面内存，原页跳走会丢）。
- 2026-11-17：**设备切换（用户选了"真的切换"）**。背景：Bambuddy 里有 H2C(id 1) 与 X1C(id 2)，PrintLab 是单设备模型（`Runtime/config.json` 的 `printer_id`），所以只显示一台。实现：`GET /api/printers`（列设备、标出当前、是否与设备卡机型一致、进行中任务）与 `POST /api/printer/select`（只改 `printer_id`，复用 PrintLab 自己的 `workspace.configure_connection`；沿用 prepared_api 的同源+会话 cookie+CSRF；拒绝：目标不在 Bambuddy 列表、Bambuddy 读不到、有进行中/结果不明的打印任务、请求体有多余字段）。前端 `PrinterPicker` 在设备卡里：下拉 + 确认框（说明设备卡机型不符与批准失效）、仅顶层页面可切、一台时不显示。**不碰设备卡**：切到 X1C 后设备卡仍是 H2C 的事实，页面与响应里都如实警告"不适用，请重新核对"；PrintLab 自带的"目标打印机已变化，需重新切片"校验保留，切换后旧切片/批准会被它拦下。验证：29 个新后端测试，6 处防线做过变异检查；PrintLab 全量 475 通过 / 42 跳过 / 7 失败（**新基线**，原 446+29；失败仍是那 7 个符号链接用例）；真浏览器：取消确认框 → 配置哈希不变；确认 → 页面与 sidecar 的读接口都变成 X1C；切回 → `config.json` 哈希回到切换前的 `36509d36…`，设备卡哈希 `5dc1b3e8…` 全程不变；零控制台错误。**PrintLab 工作台（:8018）为加载新后端已重启**（当时无任何 job）。备份在 `data/backup_before_switch/`（gitignored）。**这些 PrintLab 改动已按用户要求提交并推到用户的 fork**：分支 `feature/ai-assistant-link-and-printer-switch`，提交 `991c347`（后续 `61867fc`），远端名 `fork`（`git@github.com:cuckoo711/PrintLab.git`）；`origin` 仍是上游 AFangTeam，fork 的 `main` 未动，未开 PR；`.narrafork/` 未提交。PrintLab 本地现在停在这个分支上。
- 2026-11-17：**设备卡随设备自动切换**（用户说"你倒是自动切换呀"，嫌只弹警告）。之前故意不碰设备卡是怕覆盖 H2C 的配置；这次做成不会覆盖的版本：每台打印机的卡各存一份在 `Library/Devices/printer-<id>/`（`device.json`+`installed.md`，已被 PrintLab 的 .gitignore 的 `Library/Devices/*/` 规则忽略，不会进 git）。切换时：当前卡**原样（字节级）**存档到 `printer-<当前id>/`；目标有存档就**原样还原**，没有就建一张**空白卡**（只有 Bambuddy 报告的名称、机型，`verification_status: unconfigured`，`user_confirmed`/`installed` 为空，**不编造供料/喷嘴/AMS，也不凭空生成 installed.md**）。任何一步失败都把 config、`X2D/device.json`、`X2D/installed.md` 全部还原，不留半截状态。`GET /api/printers` 多了 `has_card`；确认框与提示语改成如实说明"卡会换、H2C 的卡原样保存、X1C 没有卡就建空白卡"。验证：36 个后端测试；8 处防线变异检查（不存档、不还原、空白卡编造供料、旧 notes 泄漏进空白卡、失败不回滚、回滚漏还原、活动任务拒绝被删、CSRF 被删）；PrintLab 全量 482 通过 / 42 跳过 / 7 失败（**新基线**，失败仍是那 7 个符号链接用例）；真浏览器：取消 → 三个文件哈希不变；切 X1C → 页面与空白卡正确、页面不再有"机型不一致"警告、`printer-1/` 里是 H2C 原卡；切回 → config / device.json / installed.md 三个哈希全部回到原值（`36509d36…` / `5dc1b3e8…` / `218f8ca1…`），零控制台错误。已提交并推送到用户 fork 的 `feature/ai-assistant-link-and-printer-switch`，提交 `61867fc`。**注意**：X1C 现在有了一张空白卡（`printer-2/` 里还没有，要等下次从 X1C 切走时才存档；X1C 的卡由用户在 X1C 上核对后补，我们不替它填）。
- 2026-11-17：**切换设备时自动同步 Bambuddy 能读到的字段**（用户问"设备卡不应该直接从 Bambuddy 同步吗"，选了自动同步）。查证：H2C 的卡里本来没有任何 Bambuddy 同步来的字段（`observed` 为空、`connection` 为空、状态 `unconfigured`），`user_confirmed` 里的喷嘴/AMS/供料是我按用户的话手写的；PrintLab 自己有 `onboarding adopt-device` 但从没跑过。Bambuddy 实际能给：机型、名称、固件、喷嘴类型与口径、AMS 单元（`ams_type`：1=AMS、3=AMS 2 Pro、4=AMS HT）及其挤出机对应、开发者模式、SD 卡；**给不了**：备用喷嘴（如 0.6mm）、左右方向说明、打印板型号、FTS。实现：切换后调用 `onboarding.adopt_device` 写 `observed`/`connection`，再加 `observed_hardware`（喷嘴、AMS 单元）；**只写观测，绝不写 `user_confirmed`**；未知 AMS 类型显示为 `type N` 不猜，空喷嘴槽保持为空；Bambuddy 读不到、或打印机在两次读取之间掉线时，切换照样成功并在提示里说明"设备卡没有刷新"。实测 H2C 的 Bambuddy 报告与用户所说一致（AMS 2 Pro×2 + AMS HT，挤出机 0/0/1，两个 HS01 0.4）；X1C 报告为单个 AMS→挤出机 0、HX01 0.4、第二喷嘴槽为空。验证：44 个后端测试；10 处防线变异检查（中途发现 2 处未被覆盖，补了测试后均抓到）；PrintLab 全量 490 通过 / 42 跳过 / 7 失败（**新基线**）；真实 API 来回切：用户确认的内容不变、notes 文件字节还原、config 哈希还原、卡里无 access_code/serial。已提交推送 fork 分支，提交 `ceb5d1f`。**注意**：切换后 H2C 卡的哈希不再是 `5dc1b3e8…`（多了观测区，正常）；H2C 的备份仍在 `data/backup_before_switch/`。
- 2026-11-17：**隐藏 PrintLab 设置页的"让 Agent 接着配置"按钮**（用户问它是不是多余；我查了：按钮只是把一段提示词复制给外部 agent，让它建 Mike/Sarah 聊天、读设备与材料、登记耗材——前两项已被我们自己的 agent 与设备卡同步取代，但"问用户三个问题"那一半没有被取代；我给了三个选项，用户先选了"指向我们的 agent"，随后又明确说"直接隐藏这个按钮"，**以最新这条为准**）。改动：`Harness/studio/src/Onboarding.jsx` 删除按钮、`copySetup`、相关状态与未用的图标导入；`scripts/verify_browser.py` 里原来断言该按钮存在的一行改为断言它不存在。**页面其余部分不变**，包括"首次会话需要补齐的信息"里的三个待答问题（`cloud_needs`、`additional_materials`、`usage_goals`）——这三个问题现在**没有任何入口可以回答**，是已知缺口：要答时用户直接告诉我，或之后让 sarah 经一个受限写工具记录（未做，需用户同意）。验证：PrintLab 全量 490 通过 / 42 跳过 / 7 失败（基线不变）；真浏览器确认按钮数为 0、角色/下一步/共同资料/设备区块都在、零控制台错误；`scripts/verify_browser.py` 用临时依赖目录 + 本机 Edge 跑到 `ok: true`（11 个页面都通过，随后它调用的 `verify_prepared_browser.py` 因 Playwright 自带浏览器没装而失败，与本改动无关，该脚本不涉及设置页）。已提交推送 fork 分支。
- 2026-11-17：**隐藏角色相关的引导**（用户贴了配置页与总览页的截图，选了"隐藏角色相关的全部提示"）。原因：PrintLab 的"待建立"指的是它设想的外部 agent 聊天（Mike/Sarah），我们不用，所以它们永远是待建立；若直接标成已完成就得伪造"聊天已创建"的记录，所以只在前端藏、不改后端数据。改动：`Onboarding.jsx` 去掉两张角色卡与"接下来"里 `kind==='role'` 的条目，删掉没用的 `roleStates`；`main.jsx` 总览的"接着配置你的工作台"卡片只在仍有非角色待办时出现，按钮文字改为"查看配置与下一步"；`scripts/verify_browser.py` 改为断言 Sarah/Mike 两个标题不存在。**保留**："我的设备与材料"、"共同资料"、以及三个仍需用户回答的问题（`cloud_needs`、`additional_materials`、`usage_goals`，折叠在"首次会话需要补齐的信息"里）。注意：**总览的引导卡片现在会一直显示**，因为那三个问题还没回答（后端 `next_actions` 里的 `interview` 条目）；回答并记录后它才会消失。验证：PrintLab 490 通过 / 7 旧失败；真浏览器确认配置页与总览页都不含 Sarah/Mike/待建立/创建与首次介绍、三个问题仍可展开、零控制台错误；`verify_browser.py` 的页面部分 `ok: true`。已推送 fork 分支（提交见 `git log`）。
- 2026-11-17：**"新想法"弹窗改为直接交给我们的 agent**（用户贴图问"怎么还是回到会话粘贴"，选了"弹窗直接跳到我们的 agent，建项目仍由你运行命令"）。原来：弹窗把需求拼成提示词复制到剪贴板，让用户粘贴给外部 agent。现在：PrintLab 弹窗的按钮变成"在 AI 助手里继续"，在新标签页打开 `http://<当前主机>:8019/chat#draft=<编码后的草稿>`；聊天台 `app.js` 在加载时**只读一次** `location.hash`，立刻用 `history.replaceState` 把它从地址栏清掉（地址只剩 `/chat`，刷新后不会回来），草稿只放进输入框、**不自动发送**、不存储、不当标记渲染；非换行的控制字符被丢弃，长度上限 2000，格式坏了就忽略；用 `#` 而不是 `?`，所以不进服务端日志和 Referer。登录令牌仍只在页面内存里。登录后自动选中 `project` 角色（没有这个角色就保持当前选择）。`project` 角色新增 `printlab_status` 工具与提示词：先查已有项目，**不能建项目**，需要建时只给用户一条 `printlab new "名称" --kind functional --brief "…"` 命令由用户自己运行，不得声称已创建。**没有新增任何写工具，agent 仍严格只读。** 验证：629 测试；真浏览器冒烟 67 项连跑 3 轮（含 8 项草稿检查）；变异检查 5 处（不清地址、自动发送、无长度上限、保留控制字符、当标记渲染），其中"保留控制字符"一项最初只被浏览器测试抓到，补了单元测试；真模型（mimo）用用户贴图里的那个想法跑了一遍：它查了项目列表（空）、指出"孔径 6mm + 间距 2.5mm 物理上不成立"并要求确认是不是 25mm、列出缺失尺寸，最后给出一条 printlab new 命令，**没有创建任何东西**（PrintLab 的 Project/ 仍为空，审计里只有只读调用）。PrintLab 一侧已提交推送 fork 分支，提交 `264198f`；`styles.css` 因换行符被 git 误标为已修改，内容与 HEAD 逐字节一致，已规范化，未提交。
- 2026-11-17：项目许可定为 PolyForm Noncommercial 1.0.0（用户先选了 MIT，随后问有没有禁止商用且署名的，改选此项；MIT 版本只在本地，从未提交）：新增 `LICENSE`（含 Required Notice 署名与商用联系说明）、`pyproject.toml` 加 `license`/`license-files` 并把构建要求抬到 setuptools>=77、`docs/LICENSES.md` 加说明。
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
- P3-4/P3-5 未做：没有会话存储、没有 HTTP 入口去跑 Agent、没有聊天台页面、没有流式输出。（搜索工具已在 P3-5 完成）`AgentRunner.stream()` 目前是"跑完再依次吐事件"，不是真流式。
- Agent 现在只有只读工具；`Ceiling.allow_write` 恒为 False，写类工具（handoff 等）一个都没注册。
- 角色文件里的 `model` 目前留空，运行时必须传 `model`；还没有"默认模型"配置。
- 没有对话长度压缩；历史只截最近 60 条。
- 工具结果截断是按字符的粗截断，`status` 与 `context` 的完整结果常常超过 12000 字符，模型可能看不到后半段。后续考虑按字段裁剪（`status` 的 `material_slots` 与 `onboarding.inventory` 占了大头）。
- 聊天台只有最基本的功能：没有 Markdown 渲染（刻意：先保证纯文本安全）、没有重命名/删除会话按钮（API 有 `DELETE /api/sessions/{id}`）、管理后台在 `/admin`（P5 已做）。
- "流式"是事件流（开始、工具调用、文本、结束），**不是逐 token**：整段回复在模型返回后一次发出。
- 页面没有做可访问性的人工验证（只有标签、live region、键盘焦点样式的静态检查与一次真浏览器冒烟）；不能据此宣称符合 WCAG，完整验证需要辅助技术手工测试。
- 同一页面里令牌用输入框传入，**没有登录/会话机制**；任何拿到 `data/admin_token` 的本机进程都能调 API（文件已收紧到当前用户 + SYSTEM）。
- 只有 mimo 一家做过真实验证；其他供应商的真实行为未知。
- P6 只做了依赖锁定与许可清单（见上）；"全新机器按文档安装"只在本机用临时虚拟环境验证过，没有在别的机器上验证；没有 Windows 服务化。
- **P4-b 已做（见 §7）；仍未做的**：IMAP 收信、Agent 之间互发消息（现在的信箱只通到人）、让计划触发工作流、"完整小物件流程跑到待批准"。当前工作流只有一个内置的 `object-intake`，它的终点是"交接给人"，不涉及建模、切片、批准、发送。
- **工作流回答 yes 之后的交接阶段没有用真模型跑过**（到人工确认点为止已用真模型+真项目验证，见 §0）。
- **工作流的检查点没有清理机制**：`data/workflow_checkpoints.db` 会一直增长；同一线程被两个进程同时恢复的情形没有测。
- **`answer`/`retry` 的并发保护只在单进程内**（内存里的 `_busy` 集合）。多个 sidecar 进程指向同一个库时不安全；目前设计是单进程。
- **工作流的 agent 阶段每次都新开一个 agent 运行**（`session=wf-<run id>` 只用于密钥粘性），不写入聊天会话，也不进聊天台的会话列表。
- **取消正在进行的工作流阶段没有实现**：`stop` 在步骤进行中会返回 409，只能等当前步骤结束。

- **调度的 token 上限是运行间检查**：已开始的一次运行不会被切断，实测一次带工具调用的运行约 6000 token（上限 3000），所以最后一次会超出上限。
- **配置导出没有对应的导入**（有意：导入会成为另一条打开无人值守花费的路）。换机器恢复要手工，密钥重新录入。
- **`web_fetch` 只在 `PLI_WEB_ALLOW_HOSTS` 列了主机才可用**，且没有用真实网站验证过（测试用的是模拟传输）；DNS 在检查与连接之间可能变化（重绑定的窄窗口），目前靠"只访问白名单里的 https 主机"兜底。
- **调度器与工作流/聊天共用同一进程**，一个长时间运行的计划会占用 `_busy` 锁，期间其他计划本轮不跑（不会丢，只是下个 tick 再来）。