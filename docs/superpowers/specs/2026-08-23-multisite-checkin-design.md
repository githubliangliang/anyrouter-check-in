# 多站点访问令牌签到流程设计

## 目标

在保留现有 AnyRouter、AgentRouter 和 Tabitoken 独立入口的前提下，新增一个本地多站点签到入口，使用同一份独立 JSON 管理以下 New API 站点账号：

- `https://tabitoken.com`
- `https://gorouter.app`
- `https://api.justwoker.icu`

三个站点均使用访问令牌鉴权，并在站点要求 Cloudflare Turnstile 时由用户在弹出的有头浏览器中完成验证。

## 用户入口

新增脚本：

```bash
python multisite_checkin.py
```

新增配置文件：

```text
multisite_accounts.json
```

该文件加入 `.gitignore`，项目提供不含真实令牌的 `multisite_accounts.example.json` 模板。配置通过 `MULTISITE_ACCOUNTS_FILE` 覆盖默认路径。

配置格式：

```json
[
  {
    "site": "tabitoken",
    "name": "tabitoken-1",
    "access_token": "填写访问令牌"
  },
  {
    "site": "gorouter",
    "name": "gorouter-1",
    "access_token": "填写访问令牌"
  },
  {
    "site": "justwoker",
    "name": "justwoker-1",
    "access_token": "填写访问令牌"
  }
]
```

不支持把令牌放进命令行参数、日志、通知、截图、HAR 或提交内容。

## 方案选择

### 方案 A：共享多站点脚本和站点预设（采用）

使用一个脚本、一份账号 JSON，以及按 `site` 选择的固定站点预设。预设包含站点 origin、页面路径和 profile 命名空间；共享 Bearer 请求、状态判断、Turnstile 等待、结果汇总和错误脱敏逻辑。

该方案满足多账号管理需求，同时把站点差异限制在明确的配置表中，避免复制三份几乎相同的流程。每个账号按顺序运行，并使用独立持久化浏览器 profile，避免多个 Turnstile 窗口互相干扰。

### 方案 B：为每个站点保留独立脚本和 JSON

实现简单但会产生三套入口和配置，后续接口变化需要重复维护，不采用。

### 方案 C：将站点配置接入现有 AnyRouter/AgentRouter 流程

现有流程使用 Cookie/API User，鉴权和 WAF 处理边界不同。强行合并会改变既有账号格式和运行行为，不采用。

## 站点预设

三个站点目前都验证存在以下 New API 路径：

- 页面：`/sign-in`
- 用户信息：`GET /api/user/self`
- 当月签到状态：`GET /api/user/checkin?month=YYYY-MM`
- 执行签到：`POST /api/user/checkin`

请求头使用：

```text
Authorization: Bearer <access_token>
Accept: application/json
```

`gorouter.app` 的未授权响应为 HTTP 200 的业务失败 JSON，`api.justwoker.icu` 的未授权响应为 HTTP 401 和 `AUTH_UNAUTHORIZED`；脚本统一按 payload 的 `success` 和错误消息分类，不依赖单一 HTTP 状态码。

Turnstile 响应仅在页面上下文中读取，并作为一次性查询参数用于重试签到；Python 进程不打印或持久化该值。

## 运行流程

1. 读取并校验 `MULTISITE_ACCOUNTS_FILE`。
2. 按文件顺序逐个处理账号，不并发启动浏览器。
3. 为账号创建 `CHECKIN_BROWSER_PROFILE_DIR/multisite/<site>/<name>` 持久化 profile。
4. 始终以有头模式打开对应站点的 `/sign-in` 页面。
5. 在同源页面上下文中调用用户信息接口；认证失败立即结束当前账号。
6. 查询当月签到状态；已签到记录为成功，不重复提交。
7. 未签到时提交 `POST /api/user/checkin`。若返回 Turnstile 要求，提示用户在当前窗口完成验证，读取页面隐藏响应后重试。
8. 再次读取当月状态确认签到成功。
9. 关闭当前账号浏览器，继续下一个账号。
10. 输出每个账号的非敏感结果和总成功数；全部成功返回 `0`，存在失败返回 `1`，配置读取或解析失败返回 `2`。

## 错误处理

- 未知站点、站点字段缺失、空名称或空令牌：启动前配置失败。
- 令牌无效或过期：记录认证失败，不输出响应中的令牌内容。
- Turnstile 超时：记录人工验证超时。
- 浏览器、网络或页面结构异常：记录站点、账号和阶段的简短脱敏错误。
- 已签到：作为成功处理。

## 测试验收

先写测试再实现，至少覆盖：

- 默认账号文件和 `MULTISITE_ACCOUNTS_FILE` 覆盖逻辑。
- 三个合法站点预设和未知站点拒绝。
- 合法账号加载、缺少字段、空令牌、非数组 JSON 拒绝。
- 令牌和 Turnstile 值不会出现在日志或异常摘要中。
- 每个站点使用独立 profile 路径和固定 `/sign-in` 页面。
- 已签到不触发 POST；Turnstile 要求进入等待分支；超时返回失败。
- 成功、已签到、认证失败、配置错误对应的结果和退出码。

真实 Turnstile 交互不放入单元测试；通过本地手动运行验收窗口弹出、人工验证、签到确认和窗口关闭。

## 非目标

- 不修改现有 AnyRouter/AgentRouter 账号格式或签到逻辑。
- 不删除或改变 `tabitoken_checkin.py` 的现有行为。
- 不支持无头 CI 自动完成 Turnstile。
- 不实现验证码识别、第三方打码或 Turnstile 绕过。
