---
name: scheduled-task
description: Helps the user create a recurring or one-off scheduled task through conversation. Load this skill whenever the user wants something done on a schedule (every day / every week / a specific time / "remind me" / periodic reports or monitoring). It explains how to confirm requirements first, translate them into a cron expression, and then call the create_scheduled_task tool to pop the pre-filled creation window.
keywords: [定时, 定时任务, 每天, 每周, 每月, 提醒我, 定期, 周期, 监测, 盯着, 简报, 日报, 周报, schedule, scheduled, cron, recurring, reminder]
---

# 定时任务助手（Scheduled Task）

当用户想要"定期/按时"做某件事时（每天、每周、某个时间点、"提醒我"、周期性简报或监测），
用这个 skill 引导对话，并最终调用 `create_scheduled_task` 工具弹出**预填好的创建窗口**。

## 工作流（必须按顺序）

### 1. 识别意图
出现这些信号就进入本流程：每天 / 每周 / 每月 / 每隔 / 定期 / 提醒我 / 盯着 / 持续关注 /
每天给我一份…… / 收盘后 / 每个工作日 等。

### 2. 先在对话里确认三要素（最重要，别跳过）
调用工具**之前**，必须把以下三点问清楚；缺哪个就只追问哪个，不要一次抛一堆问题：

1. **做什么**（任务内容）—— 要产出什么、给谁看、什么格式。
2. **多久一次**（频率）—— 每天 / 每周几 / 每月几号 / 每隔几小时 / 只一次。
3. **具体时间**（几点、周几）—— 例如"上午 9 点""周一 10 点"。

确认齐了，用**一句话复述**让用户拍板，例如：
> "那我帮你设：**每天上午 9:00**，汇总当日世界杯赛果与次日赛程，输出一段简报。对吗？"

用户明确同意后，才进入第 3 步。

### 3. 把口语翻译成 cron 表达式
工具用**标准 5 段 cron**（分 时 日 月 周）。常见映射：

| 口语 | cron |
| --- | --- |
| 每天 9:00 | `0 9 * * *` |
| 每天 9:30 | `30 9 * * *` |
| 每周一 10:00 | `0 10 * * 1` |
| 每周五 18:00 | `0 18 * * 5` |
| 每个工作日 16:00 | `0 16 * * 1-5` |
| 每小时（第 0 分） | `0 * * * *` |

周几对应：周日=0、周一=1 …… 周六=6。
**只来一次**（如"这周日提醒我一次"）：用 `trigger_type="once"` + `fire_at`（ISO 8601，如 `2026-06-21T09:00:00`），
不要用 cron。

### 4. 把"内容"扩写成可独立执行的 prompt
`prompt` 是**每次定时触发时**下发给 agent 的完整指令——它会脱离当前对话单独执行，
所以要把内容、产出格式、数据来源、范围都写清楚，不能写"就按刚才说的做"。

示例（每日世界杯简报）：
> "汇总今天的世界杯赛况：已结束比赛的比分与关键事件、正在进行/今晚的赛程、积分榜变化。
> 用简洁的中文 Markdown 输出，分『今日赛果 / 今晚看点 / 积分榜』三段，控制在一屏内。"

### 5. 调用工具
三要素已确认、prompt 已写好后，调用：

```
create_scheduled_task(
  name="世界杯每日战报",
  prompt="<第 4 步写好的完整指令>",
  cron_expr="0 9 * * *",
  trigger_type="cron",
)
```

调用成功后，桌面端会弹出预填好的创建窗口。

## fire-and-forget 边界（务必遵守）
本工具只负责**弹出窗口**，**无法**得知用户最终点了保存还是取消。
所以调用后**只能说**："创建窗口已经弹出来了，你核对一下点保存就行 ✅"，
**绝不要**说"已经创建成功""任务已生效"之类——那是窗口里用户点保存之后的事，你看不到。

## 不要做的事
- 三要素没确认齐就调用工具（尤其是时间/频率靠猜）。
- 把非法或含糊的 cron 硬塞给工具——工具会校验失败返回错误，应回到对话把时间问清楚再调。
- 调用后谎称"已创建成功"。
