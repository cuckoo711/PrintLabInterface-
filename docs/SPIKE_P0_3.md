# P0-3 Spike 结论：LiteLLM + LangGraph + PrintLab 只读 CLI

日期：2026-11-17（系统时间）。脚本：[spike_p0_3.py](spike_p0_3.py)。

## 1. 结论

**采用 LiteLLM（多供应商调用）+ LangGraph（显式状态机）作为首选组合，进入 P1。** Agent SDK（PydanticAI 或 OpenAI Agents SDK）暂不引入：Spike 没有证据表明需要它，多一个框架就多一层兼容与许可风险。退路（自写极小状态机）保留，但目前没有触发条件。

## 2. 验证了什么

| 项 | 结果 |
| --- | --- |
| LangGraph 两节点图 `read_status -> summarize`，带类型化状态 | 通过 |
| LiteLLM 统一接口 `litellm.completion(...)` | 通过，但**只用 `mock_response`**，没有联网、没有 API key |
| 调用 PrintLab 只读命令 `status`（子进程、环境变量白名单、超时、输出上限） | 通过，约 440 ms |
| 危险子命令（`approve`、`submit`、`reconcile`）在启动子进程前被拒绝 | 通过（`PermissionError`） |
| 全部安装在仓库内 `.venv`，系统 Python 未被改动 | 通过 |
| 运行结束后 PrintLab 的 `git status` 仍为空（G1） | 通过（见 §5 的清理说明） |

## 3. 没有验证的东西（不要当作已验证）

- **没有任何真实供应商调用。** OpenAI、Claude、DeepSeek 的实际请求、流式输出、工具调用格式、结构化输出、取消、重试、key 失败分类都没测。这些放在 P2，需要用户自己填入 key。
- LangGraph 的检查点（持久化）、人工中断（`interrupt`）、失败恢复没测。P4 的"待人选择、待批准"硬停点依赖它们，**P4 开始前要单独做一次小 Spike**。
- 没有测 LiteLLM 与 LangGraph 在多线程、异步、并发下的行为。
- 没有测大输出、超时、取消传播。
- 没有做传递依赖的完整许可审查，只做了元数据层面的筛查（见 §4）。

## 4. 版本与许可（读已安装包的元数据）

| 包 | 版本 | 许可（元数据） |
| --- | --- | --- |
| litellm | 1.109.1 | MIT |
| langgraph | 1.2.22 | MIT |
| langgraph-checkpoint | 4.3.2 | MIT |
| langgraph-sdk | 0.4.14 | MIT |
| langchain-core | 1.8.1 | MIT |
| openai | 3.51.0 | Apache-2.0 |
| pydantic | 2.14.3 | MIT |
| tiktoken | 0.14.0 | MIT |
| tokenizers | 0.23.3 | 元数据 License 字段为空，Classifier 为 Apache Software License |
| httpx | 0.28.1 | BSD-3-Clause |
| fastapi | 0.163.1 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

- `litellm/enterprise/` 目录**没有**被安装到环境里（已检查），所以 LiteLLM 的商业许可部分不在我们的依赖中。
- 整个环境共 90 个包。对许可字段做关键字筛查（gpl、agpl、sspl、commons clause、proprietary、busl、elastic、空值），只有本项目自己的包因未声明许可而被标出，其余无命中。
- 局限：筛查靠包自己声明的元数据，元数据缺失或写错就查不出。`tokenizers` 就是一个字段缺失、靠 Classifier 判断的例子。**正式依赖锁定时，需要对锁定版本再做一次完整的许可扫描**（P6），并人工核对缺字段的包。
- 版本没有锁定。`pyproject.toml` 目前只声明了 fastapi、uvicorn、httpx，litellm 与 langgraph 是临时装进 `.venv` 的，**尚未写入依赖声明**。

## 5. 重要发现（直接影响适配器设计）

### 5.1 子进程环境变量白名单太窄会在 PrintLab 目录制造垃圾目录

第一次运行时，白名单只放行了 `PATH、SYSTEMROOT、COMSPEC、TEMP、TMP、USERPROFILE、HOMEDRIVE、HOMEPATH`。结果：

1. `printlab status` 返回退出码 0，但 stdout 与 stderr 都是空的，导致 JSON 解析失败。
2. 在 PrintLab 仓库根目录下出现了一个字面名为 `%SystemDrive%` 的目录，里面是 3 个 Windows 缓存文件（`ProgramData\Microsoft\Windows\Caches\*.db`）。

原因是 Windows 的 PowerShell 或 Python 依赖 `SYSTEMDRIVE`、`PROGRAMDATA`、`WINDIR` 这类变量。缺了它们，某个组件把 `%SystemDrive%` 当字面路径，在**当前工作目录**下创建了文件。这个目录是**未跟踪文件**，让 PrintLab 的 `git status` 变脏，违反了我们的 G1 红线。

处理：
- 这个目录只含这次运行产生的缓存文件（没有被 git 跟踪、3 个文件均为 10 分钟内新建），我确认后删除了。PrintLab 的 `git status` 恢复为空。
- 同样的目录在 PrintLabInterface 里也出现过一次（因为第二次实验从那里运行），同样确认后删除。
- 白名单扩充后重跑，`status` 成功，且没有再产生该目录。

**对设计的要求（写入 P1 验收）：**
1. 环境变量白名单必须覆盖 `ENV_ALLOW`（见脚本）里的 Windows 系统变量，并有单元测试覆盖"最小可运行集"。
2. 子进程的 `cwd` **不要设为 PrintLab 根目录**，而是设为 PrintLabInterface 自己的专用工作目录（如 `data/run/`），这样即使再有类似副作用，也不会污染 PrintLab。本 Spike 为了贴近 PrintLab 的路径解析把 `cwd` 设成了 PrintLab 根，这个选择应在 P1 改掉。需要先验证 PrintLab CLI 不依赖 cwd（它通过脚本路径与 `PRINTLAB_ROOT` 定位根；我读了 `printlab.ps1` 和 `core.py` 里的相关代码，但没有对所有子命令做验证）。
3. 每次调用前后对 PrintLab 做一次 `git status --porcelain` 快照比对，发现新增未跟踪文件就报警并拒绝后续写类调用。这是对 G1 的运行时守卫。
4. 空输出加退出码 0 要当作错误处理，不能当作成功。

### 5.2 CLI 的耗时
`status` 约 440 ms（含 PowerShell 启动、Python 启动、读 Bambuddy）。对聊天可以接受；如果 Agent 一轮要连调多个命令，累计延迟明显。P1 评估是否对读类数据优先走 `127.0.0.1:8018` 的 HTTP。

## 6. 后续动作

1. P1 适配器按 §5 的四条要求实现，并为此写测试。
2. 把 litellm、langgraph 写进 `pyproject.toml`（带上限的版本范围），生成锁定文件。
3. P2 前向用户要一把测试 key，才能验证真实调用；之前只能说"接口形状可用"。
4. P4 之前单独 Spike LangGraph 的检查点与 `interrupt`。
