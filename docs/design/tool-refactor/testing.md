# Tool 重构如何验证功能保留

验证分三层：先对照重构前的能力和接口，再检查执行中的关键组合，最后运行真实 ACP 任务并检查产物。通过几千项测试不能证明所有产品场景都正确；本轮独立审查又找到了原测试未覆盖的两个问题，已经补充失败复现和修复。

本页说明测试的覆盖范围。各次运行的版本、数量、命令、任务质量和成本见 [验收记录](verification.md)；最新提交的完整门禁及独立复审结论见 PR Proof。所有本地 Python 测试和构建使用 uv-managed CPython 3.11.15。

## 1. 能力是否仍然存在且可用

| 能力 | 怎么检查 | 能证明什么 | 主要测试 |
| --- | --- | --- | --- |
| 原工具、参数与配置 | 固定重构前 C1 schema；装配不同文件、命令、memory、sandbox、图像和 MCP 配置，比较实际对象与提供的定义 | 没有因搬迁丢掉原注册能力；C5 提供策略的变化单列，不偷偷改基线夹具 | `test_tool_engine_compatibility.py`、`test_tool_engine_preparation_integration.py` |
| 模型请求与执行对象一致 | 请求后修改原 schema、别名或 MCP generation，检查实际执行是否拒绝失效定义；走真实 provider 的普通/stream 恢复路径 | 模型看到的接口不会悄悄换成另一对象，原别名不会在冻结定义时丢失 | `test_prepared_tools.py`、`test_prepared_tool_provider.py`、`test_tool_engine_service.py` |
| 原 Skill 能力 | 运行原加载、激活、预加载、失败与 hash 恢复测试；比较短工具确认与原正文、作用域和资源 | 新 Tool 执行链仍调用原 Skill 实现，没有把 Skill Engine 重构混进来 | `test_skill_tool.py`、`test_skill_preload.py`、`test_skill_runtime.py`、`test_core.py` |
| 本地与 MCP 发现 | MCP 关闭/加载中时仍能发现本地工具；检查精确别名、top_k、server 过滤、冲突及下一步真正调用 | 工具延迟提供后仍可达；本地与 MCP 的权限/命名范围不会混淆 | `test_local_tool_search.py`、`test_local_tool_exposure.py`、`test_mcp_tool_search.py` |
| 原定时任务 | 对照原 Python 类、完整 schema 和 Skill 文件哈希；从真实 loop 发原名调用并检查草稿 payload、call ID、保存提示和历史恢复 | 名称、常驻提供方式与消费协议保持；恢复记录不重复调用工具 | `test_schedule_tool.py`、`test_schedule_tool_contract.py` |

`create_scheduled_task` 已按用户要求保持原样。本 PR 不再引入 `prepare_scheduled_task` 或相应前端名称迁移。

## 2. 执行过程中容易退步的组合

| 组合 | 观察的结果 | 主要测试 |
| --- | --- | --- |
| 一次调用遇到多个授权条件 | 每个不同条件各询问一次；拒绝、重复请求和上限保持；批准后进度在执行完成前到达消费者 | `test_permission_negotiation.py`、`test_tool_engine_permission_stream.py` |
| 批准时或重试排队时取消 | 当前不执行；随后复用同一真实 SkillHub Tool，仍必须重新询问，拒绝后不能安装。覆盖 direct、串行、并行入口 | `test_tool_engine_approval_lifetime.py`，6 个新增场景 |
| 并行调用与 Hook 改参 | 每个结果使用自己的最终参数；Hook 改成越界输出路径时在副作用前拒绝 | `test_tool_engine_call_records.py`、`test_hooks.py` |
| 一次调用只记录一次 | 调用记录在副作用之前写入，结果只写一次；保留 success/error/rawOutput/policyDecision，图片原始字节不进入持久日志 | `test_tool_engine_call_records.py`、`test_agent_session_persistence.py`、`test_tool_result_commit.py` |
| direct loop 没有 system 消息 | 连续两次工具调用，持久结果恰好两条且元数据完整；恢复消息与内存消息一致。另测有 system、串行和并行 | `test_tool_engine_call_records.py`，4 个新增场景 |
| 失败、超时与取消 | 已发生动作不会因普通错误自动重跑；取消/超时按原规则收尾；日志持久化错误向上传播 | `test_tool_engine.py`、`test_permission_negotiation.py`、`test_tool_engine_call_records.py` |
| 子 Agent 和后台进程 | 子 Agent 不获得父会话未允许的工具；batch_files 使用共同调用入口；原 owner、完成未读输出和失效句柄行为保留 | `test_sub_agent_capabilities.py`、`test_sub_agent_tool.py`、`test_bash_tool.py`、`test_local_tool_exposure.py` |
| 插件与生命周期 | 由真实 PluginDescriptor 提供引擎，通过外层 loop 准备和执行；替换 catalog 后绑定正确对象；关闭 run 不销毁会话资源 | `test_tool_engine_preparation_integration.py`、`test_tool_engine_service.py` |

本轮两项审查修复的失败证据：授权残留 6 个场景修复前全部失败；消息范围问题无 system 的 2 个场景失败、有 system 的 2 个对照通过。修复后定向组合测试 194 passed。准确新 Head 仍需独立执行仓库完整 preflight，不能拿旧 Head 的绿灯代替。

## 3. 真实 ACP 任务与安装包

| 实际运行 | 结果 | 不能据此声称什么 |
| --- | --- | --- |
| 原问题、附件、模型、配置固定的 main/PR 对照 | 28 次尝试全部保留，含设置失败和人工中止；每次有独立诊断，不只保留成功运行 | 28 次不等于 28 个业务场景全部通过 |
| Markdown 转 PDF（557） | 24 页 PDF，原文标题与渲染检查通过；末尾结构化回执参数错误另记 | 不能说整条任务没有错误，也不是当前 Head 重新跑过的模型任务 |
| TTS 调研（725） | 实际交付 Markdown，并核对 arXiv 引用 | 存在引用错配、指标与阈值问题，研究质量未全通过 |
| 入职培训演示稿（725） | 12 页 HTML，浏览器渲染无 JS 错误和文本越界 | 浅底要求未满足；没有 PPTX，不能算可编辑 PPTX 验收 |
| 算术/排序/原则提取 smoke | 核心答案正确，ACP 通信可用 | 没有工具调用，不能独自证明 Tool Engine |
| wheel 构建、非 editable 安装和独立进程 | 历史 725 wheel 的 918 包文件及改动源码来源核对；无源码 runner 的 ACP smoke 成功 | 未验证已发布桌面 bundle 的完整加载与点击行为；新源码须重新构建/安装后才可声称新包通过 |

附件与 metadata 的 ACP evaluator 修复在 main/PR 两侧共用，单独 113 项测试通过。历史 8c 最终完整门禁为 3844 passed、20 skipped、1 deselected，随后构建后补跑两个包内容测试通过。跳过涉及缺失本地 config/MCP、Windows 专用和 Canvas 依赖等，不能计作已覆盖的真实集成。

## 4. 仍需如实保留的限制

- 真实搜索/生图服务遇到 401，部分辅助模型请求遇到 422；相应服务未证明可用。
- 固定同 Skill/metadata 的历史对照中，PPT 总 token 从 2,449,116 增至 4,872,615，TTS 从 800,373 增至 1,803,438。常驻定义更短不代表整体更省或质量更好；没有缓存返回字段，不能推算缓存收益。
- 桌面草稿、选择回传、历史恢复的真实 UI 操作尚未验完；本轮撤回定时任务改名，减少名称迁移联调，但共享执行链的源码测试不冒充点击验收。
- Plugin 扩展接口已可用；默认引擎仍由内核兜底创建，没有完全走默认插件工厂。这个设计差异与功能失败分开记录。

这些测试提供的是具体能力和边界的证据，不是“功能完整性已被百分之百证明”的保证。新发现必须有直接复现和修复回归，合并仍需维护者结合完整 diff、准确 Head 检查及残余风险判断。
