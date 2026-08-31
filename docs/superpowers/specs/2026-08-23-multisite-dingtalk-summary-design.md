# 多站点签到钉钉汇总通知设计

## 目标

为 `multisite_checkin.py` 增加钉钉汇总通知。每次多站点签到运行结束都发送一条文本消息，并确保消息固定包含钉钉机器人安全关键字 `tabitoken`。

通知只复用现有 `NotificationKit.send_dingtalk()`，不修改 AnyRouter/AgentRouter 的通知行为，也不启用其它通知渠道。

## 通知触发

以下运行结果都会尝试发送一次钉钉通知：

- 全部账号签到成功或当日已签到。
- 部分或全部账号签到失败。
- 账号列表为空。
- 配置文件缺失、JSON 格式错误或账号字段校验失败。

通知发送失败不改变原有签到退出码。未配置 `DINGDING_WEBHOOK` 时输出简短的跳过提示，不把缺少可选通知配置视为签到失败。

## 消息格式

标题固定为：

```text
tabitoken 多站点签到汇总
```

正文包含：

- 执行时间。
- 总账号数、成功数和失败数。
- 每个账号的 `site/name` 和结果。
- 配置错误时的脱敏错误摘要。

示例：

```text
tabitoken 多站点签到汇总
执行时间: 2026-08-23 18:30:00
总计: 3
成功: 2
失败: 1

tabitoken/main: already_checked
gorouter/main: success
justwoker/main: auth_failed
```

账号结果按配置文件顺序排列。访问令牌、Turnstile 响应和 Webhook 地址不得进入标题、正文或终端错误日志。

## 实现边界

`multisite_checkin.py` 在 `load_dotenv()` 之后创建 `NotificationKit`，确保读取 `.env` 中的 `DINGDING_WEBHOOK`。

签到执行函数在处理每个账号时保留非敏感结果，用于最终汇总。结果汇总与发送拆成独立函数，便于单元测试。发送函数直接调用 `send_dingtalk()`，不会调用 `push_message()`，避免同时尝试邮件、飞书等未要求的渠道。

配置加载失败时，由 `main()` 组装配置失败汇总并尝试通知，然后保留退出码 `2`。正常签到结束后，保留现有退出码规则：全部成功为 `0`，存在签到失败为 `1`。

## 错误处理

- `DINGDING_WEBHOOK` 未设置：输出 `[NOTIFY] DingTalk notification skipped: webhook not configured`。
- 钉钉返回 HTTP 或业务错误：输出 `[NOTIFY] DingTalk notification failed: <脱敏原因>`。
- 通知失败不重试，避免脚本结束阶段长时间阻塞或重复推送。
- 通知异常不得覆盖签到异常或改变退出码。

## 测试验收

先写测试再实现，至少覆盖：

- 汇总标题始终包含精确关键字 `tabitoken`。
- 正文包含时间、总数、成功数、失败数和逐账号结果。
- 全成功、部分失败、空账号和配置错误均尝试发送一次。
- 只调用钉钉发送方法，不调用全渠道 `push_message()`。
- 未配置 Webhook 时跳过发送，退出码不变。
- 钉钉发送异常时退出码不变，且日志不包含访问令牌或 Webhook 地址。

真实 Webhook 不纳入自动化单元测试；实现完成后使用当前本地 `.env` 做一次不含访问令牌的测试通知，确认机器人关键字和消息格式生效。

## 非目标

- 不修改现有 `checkin.py` 的通知触发规则。
- 不新增钉钉签名密钥或机器人配置格式。
- 不发送访问令牌、Turnstile 响应、浏览器状态或截图。
