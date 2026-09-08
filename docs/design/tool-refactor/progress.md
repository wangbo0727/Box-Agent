# Tool PR1 实施与验证记录

## 交付边界

本分支只交付 Tool 阶段一个 PR，保留原 Skill 实现。以 [设计](design.md) 和 [实施明细](implementation.md) 为完整要求；下表是跟踪索引，不缩减原要求。主分支保持原完整能力，Tool PR 验证完成后才可合并；Skill 重构另一个 PR。维护者决定合并。

## 分支和版本

- 基准：`d2f665fb23e159e8aef6884d2e97f2eae600f38b`（upstream/main，2026-09-08 核对）。
- 分支：`codex/refactor-tool-engine`，独立 worktree。
- 历史能力参照：PR100 前 `f6bac85c431bc185c2658d140efbdb7f1b4d49f5`。
- 本次不发布新产品版本，保持上游 0.9.8；每份验证记录必须对应准确源码 SHA/工作区差异。
- 用户原 main 上的修改不迁入、不重置。证据与真实评测数据留在本地，不提交配置、密钥和日志。

## 上游增量与实施调整

1. 原设计审阅 2d06469，再检查 PR112 至 73cce30；实施起点已包含 PR111 和 PR97。
2. PR111 未修改 kernel/tool 执行主体。Engine 继续接 composition / PluginHost；不要求 ACP/CLI 自行装配。保留 AgentService、AgentRunHandle、MCPRuntimeController 的 live registry，以及 skill_runtime 的原地 preload 更新。
3. Tool 结果持久化仍在 Agent；共同提交迁移需移除对应重复责任。CLI 新增 SessionTraceWriter，诊断 trace 继续与 durable Session Log 分开。
4. 保留 run_observer 的产物 lineage 与 turn cleanup 归属，Engine 不关闭借用资源。
5. 初始 preflight 使用本机 Conda Python 3.12.8，在 pytest 收集前因 `import readline` 段错误退出（139）。单独导入复现；已安装的 CPython 3.11.15 可正常导入。仅独立 worktree 环境改用 3.11，保持 frozen lock 和完整测试范围。
6. 当前标准 ACP wrapper 要求数据集位于实现仓库内。外部固定案例先原样暂存到被忽略的 test_workspace/inputs；不绕过规定 ACP 入口。

7. 当前模型服务拒绝默认 thinking=false 对应的 reasoning_effort=none（422，3/3 smoke 在工具执行前失败）。补评测器显式 session_meta.deep_think 透传，在 baseline / PR 同用 deep_think=true；保持原模型/预算/Skill/输入，不将此 harness 修复计作 Agent 效果收益。
8. 安装的宿主已只读核对：草稿消费按 officev3_schedule_draft 与 toolCallId 去重，不依赖旧工具名；仍待 PR runtime 构建后的协议/实际交互验证。
9. 用户明确要求只用 uv，不使用 Conda。后续虚拟环境显式选择 uv-managed CPython 3.11.15，且不修改系统 Python 或个人环境。

## 完成清单

| 提交工作包 | 完成要求 | 当前状态 |
| --- | --- | --- |
| C1 | 固定基准、完整入口/能力清单、原测试与任务基线 | 进行中：固定基准完整 preflight 通过（3712 passed / 20 skipped / 1 deselected，sdist 与 wheel 构建成功）；26 个新增装配对照通过，真实 ACP 基线进行中 |
| C2 | tools/engine、唯一会话对象、准备定义/别名/目标、服务装配 | 待实施 |
| C3 | 共同执行、流式权限继续、上下文、拒绝/取消/失败政策 | 待实施 |
| C4 | 共同结果完成、唯一消息提交、原 Skill 桥、业务处理归位 | 待实施 |
| C5 | 两档暴露、本地/MCP 发现、规范名迁移、全入口收口 | 待实施 |
| C6 | 全回归、ACP 真实任务与产物、打包安装探针、实际宿主、最终 Head 门禁与 PR | 待实施 |

## 验收维度

| 维度 | 所需证据 | 状态 |
| --- | --- | --- |
| 装配与能力 | 各支持宿主/配置/子 Agent；canonical/alias/schema；eager/deferred 覆盖、profile | 待验证 |
| 请求一致性 | 自定义 schema/来源指纹保留，实际对象冻结，定义/来源失效拒绝，run close 不丢会话状态 | 待验证 |
| 授权执行 | 最终参数复核、多权限门、实时进度、并行审批顺序、取消、无盲目重放、直接调用 | 待验证 |
| 结果与恢复 | 一次 call/result、原结果通道、图片安全、参数归属、Skill active/preload/direct core、后台句柄 | 待验证 |
| 工具集合 | 本地搜索不被 MCP 等待阻塞、精确旧名可达、隐藏名保护、必要工具直接提供、子权限无扩大 | 待验证 |
| 改名与宿主 | prepare_scheduled_task 新 schema、旧名兼容、原草稿事件、历史不重放、manifest、真实宿主 | 待验证 |
| 端到端 | 固定模型/Skill/配置/预算/输入的 ACP 基线与新实现；文件、复杂搜索/委派、PPT 产物 | 待验证 |
| 收益 | 任务成功、误选、参数错误、发现轮数、schema/总 token、缓存、延迟 | 待验证 |
| 工程 | 新进程 import、完整 preflight、wheel 安装/探针、准确最终 Head、只一个 Tool PR | 待验证 |

新增失败、skip、基线已知缺陷和缺少实际宿主必须分别报告。绿灯不能替代未验证维度；运行状态不等于实际产物满足要求。
