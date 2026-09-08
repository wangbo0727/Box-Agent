# Tool PR1 实施与验证记录

## 交付边界

本分支只交付 Tool 阶段一个 PR，保留原 Skill 实现。以 [设计](design.md) 和 [实施明细](implementation.md) 为完整要求；下表是跟踪索引，不缩减原要求。主分支保持原完整能力，Tool PR 验证完成后才可合并；Skill 重构另一个 PR。维护者决定合并。代码和安装包验证已完成，桌面交互仍待补齐，暂不标记可合并；完整版本、结果和局限见 [验收结果](verification.md)。

## 分支和版本

- 基准：`d2f665fb23e159e8aef6884d2e97f2eae600f38b`（upstream/main，2026-09-08 核对）。
- 分支：`codex/refactor-tool-engine`，独立 worktree。
- 历史能力参照：PR100 前 `f6bac85c431bc185c2658d140efbdb7f1b4d49f5`。
- 本次不发布新产品版本，保持上游 0.9.8；每份验证记录必须对应准确源码 SHA/工作区差异。
- 用户原 main 上的修改不迁入、不重置。证据与真实评测数据留在本地，不提交配置、密钥和日志。

## 上游增量与实施调整

1. 原设计审阅 2d06469，再检查 PR112 至 73cce30；实施起点已包含 PR111 和 PR97。
2. PR111 未修改 kernel/tool 执行主体。Engine 继续接 composition / PluginHost；不要求 ACP/CLI 自行装配。保留 AgentService、AgentRunHandle、MCPRuntimeController 的 live registry，以及 skill_runtime 的原地 preload 更新。
3. 开工时 Tool 结果持久化仍在 Agent；现在由 kernel/tool_messages.py 提供共同提交回调，Engine 调用，Agent 对 ToolCallResult 的专门写入已移除。诊断 trace 继续与 durable Session Log 分开，保留原 flush 边界。
4. 保留 run_observer 的产物 lineage 与 turn cleanup 归属，Engine 不关闭借用资源。
5. 初始 preflight 使用本机 Conda Python 3.12.8，在 pytest 收集前因 `import readline` 段错误退出（139）。单独导入复现；已安装的 CPython 3.11.15 可正常导入。仅独立 worktree 环境改用 3.11，保持 frozen lock 和完整测试范围。
6. 当前标准 ACP wrapper 要求数据集位于实现仓库内。外部固定案例先原样暂存到被忽略的 test_workspace/inputs；不绕过规定 ACP 入口。

7. 当前模型服务拒绝默认 thinking=false 对应的 reasoning_effort=none（422，3/3 smoke 在工具执行前失败）。补评测器显式 session_meta.deep_think 透传，在 baseline / PR 同用 deep_think=true；保持原模型/预算/Skill/输入，不将此 harness 修复计作 Agent 效果收益。
8. 安装的宿主已只读核对：草稿消费按 officev3_schedule_draft 与 toolCallId 去重，不依赖旧工具名；仍待 PR runtime 构建后的协议/实际交互验证。
9. 用户明确要求只用 uv，不使用 Conda。后续虚拟环境显式选择 uv-managed CPython 3.11.15，且不修改系统 Python 或个人环境。
10. 基线评测发现附件虽已复制，却没有进入 ACP prompt。评测器现在保持原问题文本，附加标准 resource_link 和路径索引；baseline / PR 使用同一修复，附件字节不变，也不放宽 allowed_dirs。旧的缺失输入尝试保留，不能用于产物对照。
11. 上游 main 又推进到 25868b4（PR106，PPTX Skill 导出修复）。集成前 rebase；PPT 另补同版本 Skill 的 main 对照，旧 d2 基线保留。没有把上游 Skill 修改作为本 PR 的重构收益。
12. 实施中修复了两项直接影响共同链路的问题：授权等待期间取消后不得再执行副作用；eager MCP 也必须保留并检查本次定义的 generation。新增失败回归先复现，再验证修复。
13. scheduled-task 只改三处工具引用。没有在总 system prompt 额外重复定时任务说明；原提示长度约束继续生效。生成器已运行，scheduled-task 不在当前打包 manifest 的 12 个条目中，仅时间戳变化不纳入补丁。
14. C2–C5 的服务装配、共同执行、结果提交和发现策略相互依赖，作为一个 Tool 子系统实现提交审阅；C1 对照夹具和 ACP 评测器修复独立提交。仍只交付一个 Tool PR。
15. 提交的代码索引停在 fb261b3，已按实际源码核对涉及模块；当前没有可调用的 /understand 生成器，未手改 graph/meta/fingerprints。索引刷新待具备该工具的环境执行。
16. 独立审查发现 provider 的 SenseNova 调用恢复也读取 Tool.aliases。725e2d8 在冻结定义中补上不可变别名，新增普通/stream 实际 provider 路径的回归；不额外把旧名放入模型 schema。
17. PR 首次 TTS 在 plan_write 后等待客户端批准。保留原尝试，另建 main/PR 同样显式 auto_approve_plan=true 的补对照，避免把协议完成错当文件交付。
18. 隔离桌面副本的 ad-hoc 签名通过静态验证，但实际启动被 dyld library validation 拒绝。源码、wheel、ACP 均已验证，实际草稿/决策交互仍未完成；原应用与系统安全设置保持原样。

## 完成清单

| 提交工作包 | 完成要求 | 当前状态 |
| --- | --- | --- |
| C1 | 固定基准、完整入口/能力清单、原测试与任务基线 | 已固定：d2 完整 preflight 3712 passed / 20 skipped / 1 deselected，sdist 与 wheel 成功；26 个新增装配对照通过。三条 smoke 完成；三条真实任务及失败尝试均保留，已由独立 Agent 诊断 |
| C2 | tools/engine、唯一会话对象、准备定义/别名/目标、服务装配 | 已实现并做定向验证；冻结 schema 与真实对象、别名、来源、generation，PluginHost 可注入，关闭不销毁借用资源 |
| C3 | 共同执行、流式权限继续、上下文、拒绝/取消/失败政策 | 已实现并做定向验证；主循环、公共 runtime、子 Agent 批量读取共用单次调用与权限链；批准后进度实时转发，取消不启动下一次尝试 |
| C4 | 共同结果完成、唯一消息提交、原 Skill 桥、业务处理归位 | 已实现并做定向验证；每条调用拥有最终参数，串并行共用收尾；日志写方唯一；原 Skill、图片、资源、搜索与产物行为迁移到所属模块 |
| C5 | 两档暴露、本地/MCP 发现、规范名迁移、全入口收口 | 已实现；全量与真实 ACP 任务验证可达，定时任务新规范名与旧名兼容。真实宿主尚未完成运行验证 |
| C6 | 全回归、ACP 真实任务与产物、打包安装探针、实际宿主、最终 Head 门禁与 PR | 部分完成：725 全量 3846 passed；wheel 非 editable 安装及 918 文件探针、真实 ACP 与独立产物诊断完成。桌面交互与最终发布门禁待补；PR 保持 Draft |

## 验收维度

| 维度 | 所需证据 | 状态 |
| --- | --- | --- |
| 装配与能力 | 各支持宿主/配置/子 Agent；canonical/alias/schema；eager/deferred 覆盖、profile | C1 固定夹具 + C5 明确差异夹具；725 完整 preflight 通过 |
| 请求一致性 | 自定义 schema/来源指纹保留，实际对象冻结，定义/来源失效拒绝，run close 不丢会话状态 | prepared_tools / preparation_integration / service 用例已覆盖 |
| 授权执行 | 最终参数复核、多权限门、实时进度、并行审批顺序、取消、无盲目重放、直接调用 | permission_stream / permission_negotiation / sub_agent / call_records 用例已覆盖 |
| 结果与恢复 | 一次 call/result、原结果通道、图片安全、参数归属、Skill active/preload/direct core、后台句柄 | call_records / result_commit / 原 pipeline 与 Session Log 用例已覆盖；实际 Agent 多次权限尝试仍只有一次 call/result，图片只进入瞬态模型上下文 |
| 工具集合 | 本地搜索不被 MCP 等待阻塞、精确旧名可达、隐藏名保护、必要工具直接提供、子权限无扩大 | local_tool_search / local_tool_exposure / MCP / ACP / 子 Agent 用例已覆盖 |
| 改名与宿主 | prepare_scheduled_task 新 schema、旧名兼容、原草稿事件、历史不重放、manifest、真实宿主 | 源码与恢复用例通过；已核对安装宿主 1.0.28 的实际消费代码，未声称已完成宿主重启或实际交互 |
| 端到端 | 固定模型/Skill/配置/预算/输入的 ACP 基线与新实现；文件、复杂搜索/委派、PPT 产物 | d2 与 PR 完成；258 同 Skill PPT、同 auto-plan TTS 补对照完成。PDF、Markdown、HTML 文件交付与内容质量分开记录 |
| 收益 | 任务成功、误选、参数错误、发现轮数、schema/总 token、缓存、延迟 | 已从 trace 提取；首轮定义 30→16–18，但两条补对照的总 token 增加。没有缓存字段，不推断缓存或整体效率收益 |
| 工程 | 新进程 import、完整 preflight、wheel 安装/探针、准确最终 Head、只一个 Tool PR | 评测器 113 passed；725 全量 3846 passed / 18 skipped / 1 deselected；sdist/wheel、安装探针与 wheel ACP smoke 通过。正式 required CI/review 不能由本地结论替代 |

## 当前真实基线怎样解读

| 任务 | 已确认的交付 | 仍存在的问题 |
| --- | --- | --- |
| 三条纯文本 smoke | 算术、排序、原则提取结果符合输入 | 外部辅助继续判断服务不接受 thinking=false；与 Agent 交付分别记录 |
| TTS 调研 | 实际生成约 22 KB Markdown；26 个 arXiv 引用已核对 | 部分方法、阈值和抽样说明质量不足；搜索服务 401 后用实际 arXiv 查询替代 |
| 入职培训 PPT | HTML 与 deck.json 共 12 页，已用 Chromium 渲染 | 一处空图和未经输入支持的公司政策；旧 Skill 基线不替代最新 main 的同 Skill 对照 |
| Markdown 转 PDF | 已确认最终尝试完整收到并读取原附件 | 自然结束仍没有 PDF；脚本转换错误与环境依赖错误分别诊断。早期人工中止和缺失附件尝试不能当自然基线 |

完整输入、输出、不可变 attempt、渲染、诊断和脱敏清单保存在本地 TestRun/tool-refactor-20260909，未纳入 Git。基线失败不自动使新版本通过；PR 已独立运行并检查实际产物，结果见 [验收结果](verification.md)。

新增失败、skip、基线已知缺陷和缺少实际宿主必须分别报告。绿灯不能替代未验证维度；运行状态不等于实际产物满足要求。
