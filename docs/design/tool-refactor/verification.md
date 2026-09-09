# Tool PR1 验收结果

本次保留原 Skill 实现。下文记录每个历史版本实际执行过的验证；最新 PR Head 的完整门禁与独立审查结论以 PR Proof 为准，不把旧版本结果当作新版本实测。工具能力可达、文件交付、产物质量和桌面消费分别验收。

2026-09-09 根据用户要求撤回定时任务改名，恢复原 create_scheduled_task 的名称、Python 类、schema、Skill 原文及常驻提供方式。新增原样对照及原草稿/历史恢复回归，不再引入改名的前端联调。独立 review 另发现一次性授权在取消后残留（P1）与无 system 前缀时工具结果重复持久化（P2）；均补失败复现后修复，精确提交和复审结果记于 PR Proof。

## 1. 版本与环境

| 对象 | 固定版本或说明 |
| --- | --- |
| 历史能力参照 | PR100 前 `f6bac85c431bc185c2658d140efbdb7f1b4d49f5` |
| 实施基线 | `d2f665fb23e159e8aef6884d2e97f2eae600f38b`，保留原 Tool/Skill 代码 |
| 集成主分支 | `25868b4c13f81f8a6fe491ab3fc859444bdf85ef`；已 rebase，增量是上游 PPTX Skill 修复 |
| 完整实现 | `557dcbd33c4685cb72db74000985018b0dbae274` |
| 别名兼容修复 | `725e2d873b4c468f1cc86ce40cf15f3710c3d080`；只有定义视图增加别名快照及回归测试 |
| Python / 依赖 | uv-managed CPython 3.11.15，`uv sync --frozen --all-extras`；不使用 Conda |
| 评测入口 | 所有模型任务通过 `test_workspace/run_acp_eval.py`；独立 profile、工作区和不可变 attempt |
| 真实模型 | SenseNova-Flash-Lite-20260727-v39-fp8-step4k-dpov2-mtp，provider=openai，输出上限 64000、上下文 264144、memory=false；双方显式 session_meta.deep_think=true |

本次不发布新的产品版本，包版本沿用上游 0.9.8。安装证明必须同时带源码 SHA 和 wheel hash，不能只看版本号。原 main 工作区和已安装应用保持原样。d2/258 评测树叠加了同一六文件 evaluator 修复，Agent/Skill 代码未改，不能称整棵基线 checkout 为 clean。后续文档提交的准确 Head 门禁另记于 PR Proof，不把 725 的结果标成另一个 SHA 的运行结果。

## 2. 源码和行为证据

| 检查 | 实际结果 | 能证明什么 |
| --- | --- | --- |
| d2 基线完整 preflight | 3712 passed、20 skipped、1 deselected；sdist/wheel 成功 | 原测试基线，不代表所有任务产物合格 |
| 557 完整 preflight | 3841 passed、18 skipped、1 deselected、1 warning；427.84 秒 | 完整重构可通过原仓库门禁 |
| 725 完整 preflight | 3846 passed、18 skipped、1 deselected、1 warning；427.64 秒；sdist/wheel 成功 | 修复后的完整源码回归 |
| ACP 评测器测试 | 113 passed | 显式 metadata、原附件及路径索引正确进入标准 ACP；基线和 PR 共用修复 |
| Provider 别名回归 | 新增 5 个用例先失败；修复后相关 114 个用例通过 | 普通/stream 的 SenseNova 恢复路径保留旧名；模型 wire 仍只提供规范名 |
| 725/8c 当时的本地审查 | provider 别名 P1 当时已修复；该轮未发现后续两项问题 | 历史审查不保证无缺陷；本轮新的独立 review 与修复必须单独复验 |

完整命令是 `UV_PYTHON=/Users/wangbo4/.local/bin/python3.11 bash general_review/ci/preflight.sh`。路径指向本机 uv 管理的解释器；其他机器应选择自己的 uv-managed Python。唯一 deselect 是仓库脚本原有的 unreachable MCP timeout 用例，没有为本 PR 扩大排除范围。

新增组合回归覆盖：冻结定义与真实执行对象、eager/deferred generation、旧名与隐藏名范围、最终 Hook 参数复核、授权后实时进度、授权等待期间取消、并行审批顺序、失败不重放、一次 call/result 持久化、原 Skill 加载与恢复、直接 runtime/子 Agent 路径、低频本地发现和原定时草稿。它们补在原 suite 上，不以“新方法被调用”替代原能力验证。

已有测试的局限仍保留：`tests/test_agent.py` 的部分错误分支返回布尔值而非断言，无法独自证明业务成功；`tests/test_core.py` 的自动注册依赖末尾集中入口，新增方法必须确认被收集。实际产物检查另做。

## 3. ACP 任务及产物

基线与 PR 使用相同原问题、模型、预算及对应 Skill。附件修复保留原 Markdown 的 25,722 字节与 SHA256 `3dccdc0c83f87665440c721dcb9d35a2b59c18f837114401ae14d9353640e3fb`，不放宽 allowed_dirs。旧的附件缺失、模型 422、启动路径冲突尝试完整保留，不用于自然交付的对照。

| 任务 | 主分支结果 | PR 结果 | 验收判断 |
| --- | --- | --- | --- |
| 算术、排序、原则提取 smoke | d2 的三个任务核心答案正确 | 557 核心答案正确；725 安装 wheel 的独立 smoke 也正确 | ACP/模型基本通信通过；这些问题没有工具调用，不能单独证明 Tool Engine |
| Markdown 转 PDF | d2 完整附件自然运行结束，未交付 PDF | 557 交付 24 页 PDF，671,026 字节；75 个原文标题可检索；逐页渲染无明显裁切/重叠 | PDF 交付通过；末尾结构化回执参数错误单列。725 的改动只修复 provider 别名，本任务没有冒称在 725 重跑 |
| TTS 调研 | d2 交付约 22 KB Markdown；258 补对照交付 18,251 字节、26 个可核对 arXiv 引用 | 725 补对照交付 19,831 字节 Markdown、34 条 arXiv ID；其中 UTMOS 标题错配到综述 | 文件生成及公开 arXiv 检索/抓取路径可用；原搜索服务仍未通过，PR 研究内容质量部分不符 |
| 12 页入职培训 | d2 与 258 均交付 12 页 HTML；258 使用与 PR 一致的 193 个 PPT Skill 文件 | 725 交付 12 页 HTML，2,506,914 字节；Chromium 0 JS error、0 文本越界 | 两边保留演示稿生成能力；PR 全蓝底偏离浅底要求、组织图偏小，质量部分不符。没有 PPTX，不算可编辑 PPTX 验收 |

TTS 首次 PR557 在 `plan_write` 后等待客户端批准，不能当作模型自行放弃，也不能算交付成功。另建同条件补对照，双方仅显式加入 `prompt_meta.auto_approve_plan=true`；它与默认客户端尝试分组，不覆盖原 attempt。补对照双方实际均未选择 plan_write，不能声称它们验证了自动批准执行分支。

环境局限在两侧分别记录：外部搜索/生图服务 401、辅助模型拒绝 thinking=false 的 422、脚本依赖及权限拒绝。首个 d2 PDF 因实际启动 brew 安装而人工终止，单列为受干预尝试；后续 PDF 使用相同的私有 Pandoc 3.11/Typst 0.15.1。brew guard 只约束 PATH，未阻断绝对路径调用，不能宣称为系统级隔离。没有通过修改固定 Skill、悄悄更换模型或删除失败尝试获得通过结果。每个 case 的 `diagnosis.md` 由运行者之外的 Agent 写入；文件、语义和协议状态分别记录。

## 4. 工具集合与运行成本

| 可比组 | 首轮定义数：main → PR | 定义 token 估算：main → PR | 任务总 token：main → PR | 结果 |
| --- | --- | --- | --- | --- |
| 258 / 725 PPT，同 Skill | 30 → 18 | 9866 → 6815 | 2,449,116 → 4,872,615 | 定义缩短，整体任务成本升高；不能声称更省 |
| 258 / 725 TTS，同 auto-plan metadata | 30 → 16 | 9869 → 6372 | 800,373 → 1,803,438 | 低频工具被发现后可用，任务路径与成本仍有波动 |

定义估算对 trace 中的工具 schema 使用紧凑 JSON 和 `cl100k_base`，**不是 SenseNova tokenizer 的精确计费**。总 token 来自真实 provider usage。Provider 未返回缓存字段，缓存命中未知，不能当零命中或推算节省。Tool 错误次数不能自动等同“误选工具”，仍需读实际输入与结果。

C2–C4 先用固定 C1 定义、原集合与组合回归证明结构兼容；C2–C5 最终共同运行模型任务，没有另造一套长期配置开关做模型消融实验。因此这组数据证明可达与交付路径，不能分离每项结构变化的因果收益，更不支持宣称整体质量/速度已提高。

## 5. 构建、安装与桌面边界

725 wheel SHA256：`d0223e847311ca9713c43aa4058468fce2bc3a2e7e6a21848dcb9782011bd9dc`。

| 边界 | 已确认事实 |
| --- | --- |
| 构建 | sdist 与 wheel 包含新模块，保持 0.9.8 |
| 安装 | 两个私有 uv 环境非 editable 安装；同版本使用 `--reinstall` 避免误用旧包 |
| 探针 | 918 个包文件与 wheel 逐字一致；36 个改动源码与 git 725 一致；隔离 Python import、兼容导出和别名快照正常 |
| ACP 新进程 | 没有 box_agent 源码的独立 runner 使用已安装 wheel，smoke 完成，32,444 tokens、2 次计费响应 |
| 桌面消费代码 | 只读核对已安装 1.0.28：定时草稿按 `officev3_schedule_draft` 与调用 ID 消费/去重，不按旧工具名；决策请求保留原 ID/metadata |
| 隔离宿主启动 | 路径适配副本的首次启动被 dyld library validation 拒绝；ad-hoc 与 hardened runtime 无真实 Team ID，尚未进入 main、ACP 或 UI。原应用没有替换/重启 |
| 尚缺的实际交互 | 原桌面草稿、决策返回与历史恢复的真实点击操作未测；定时任务名称迁移已撤回，不能仍以新规范名联调为缺口 |

隔离副本只适配路径、runtime 位置与测试系统集成，不改原 renderer/IPC 业务逻辑；即使后续在开发宿主验证成功，也必须标为“复用原消费代码的开发宿主”，不能写成未经改动的发布应用已经验证。没有修改系统安全设置，也没有使用个人签名私钥。

## 6. 合并条件与回退

准确最终 Head 的 required CI/review 及维护者确认仍是合并条件。真实桌面未实测、模型任务质量与运行成本的残余风险须在 PR 明示；Computer Use 只是可选验收手段，不是 Tool Engine 依赖。本轮保持 Draft 等待修复后的独立审查与门禁。当前仓库索引停在 fb261b3；源码已直接核对，没有手工伪造图谱刷新。原 Skill Engine 的发现/调度问题不在本 PR 中悄悄扩展。

没有 Session Log 格式或配置迁移。回退整个 Tool PR/运行时构建，按原部署方式结束活动任务并启动上一构建；历史调用不重执行，外部已完成操作不回滚。不在请求中途切换到旧执行器补做副作用。

脱敏索引、日志、官方 ACP attempts、产物、渲染和独立诊断位于本地 `TestRun/tool-refactor-20260909`；不提交密钥、配置、个人数据和原始日志。PR Proof 给出最终 Head 与当前剩余门禁，本文保留每份历史证据实际对应的 SHA。
