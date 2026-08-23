# Tabitoken 独立签到流程设计

## 目标

为 `https://tabitoken.com` 增加独立的本地签到流程，使用访问令牌鉴权，并在站点要求 Cloudflare Turnstile 时由用户在弹出的浏览器中完成验证。

现有 `checkin.py`、`accounts.json`、AnyRouter 和 AgentRouter 流程保持不变。Tabitoken 使用单独的账号文件和单独的命令入口。

## 用户入口

新增脚本：

```bash
python tabitoken_checkin.py
```

新增配置文件：

```text
tabitoken_accounts.json
```

该文件加入 `.gitignore`。项目提供不含真实令牌的模板 `tabitoken_accounts.example.json`。

配置格式：

```json
[
  {
    "name": "tabitoken-1",
    "access_token": "填写访问令牌"
  }
]
```

脚本通过 `TABITOKEN_ACCOUNTS_FILE` 指定文件路径，默认使用当前目录的 `tabitoken_accounts.json`。不支持把令牌放进命令行参数或通知内容。

## 方案选择

### 方案 A：独立脚本，浏览器内 API 流程（采用）

每个账号都使用独立的持久化浏览器 profile。脚本以有头模式打开 Tabitoken 登录页，在页面上下文中使用 Bearer 令牌调用用户信息和签到接口。若签到接口要求 Turnstile，用户完成页面现有的 Turnstile 控件后，页面上下文立即使用该一次性结果重试签到。

该流程不依赖 `/profile` 的浏览器登录会话，因为网站生成的 API 访问令牌和前端短期登录令牌不是同一种状态。优点是 Bearer 令牌和 Turnstile 验证都在同源浏览器上下文内使用，不需要在 `httpx` 与浏览器之间迁移状态；不会把短期 Turnstile token 写入日志或配置。缺点是签到时需要本机有图形界面，并且站点再次要求验证时需要人工操作。

### 方案 B：先 API 请求，失败后浏览器兜底

先用 Bearer 令牌直接请求签到接口，遇到 403 或 Turnstile 错误再启动浏览器。该方案在没有 WAF 时可能更快，但需要在两套认证状态之间切换；当前站点已启用 Turnstile，收益有限，故不采用。

### 方案 C：后台自动解 Turnstile

依赖第三方验证码服务或绕过方案。它会增加账号和令牌泄露风险，也不符合本项目的本地人工验证约束，明确不采用。

## 运行流程

1. 读取并校验 `TABITOKEN_ACCOUNTS_FILE`。
2. 按文件顺序逐个处理账号，不并发启动浏览器，避免多个 Turnstile 窗口互相干扰。
3. 为账号创建独立 profile 目录：
   `CHECKIN_BROWSER_PROFILE_DIR/tabitoken/<账号名>`。
4. 始终以有头模式启动浏览器，不复用现有 `CHECKIN_HEADLESS` 设置，也不提供后台解题模式。
5. 打开 `https://tabitoken.com/sign-in`，等待站点和 Turnstile 控件加载。
6. 在页面上下文中调用 `GET /api/user/self`，请求头使用 `Authorization: Bearer <access_token>`；认证失败时停止该账号。
7. 在页面上下文中调用 `GET /api/user/checkin?month=YYYY-MM`：
   - 当日已签到：记录成功并关闭浏览器。
   - 当日未签到：继续执行签到。
8. 在页面上下文中调用 `POST /api/user/checkin`。若返回需要 Turnstile，终端输出不含令牌的提示，等待用户完成页面上的验证控件。
9. 页面上下文取得 Turnstile 控件的一次性响应后，直接调用 `POST /api/user/checkin?turnstile=<response>`；Python 只接收脱敏后的签到结果，不打印或持久化该响应。
10. 再次读取当月签到状态确认当日已签到；已签到视为成功，认证错误、签到失败或超时视为失败。
11. 关闭当前账号的浏览器，继续下一个账号。
12. 最终输出成功数、失败数和每个账号的非敏感原因。

## 浏览器和 Turnstile 约束

- 令牌只在进程内存中组装为请求头，不写入浏览器截图、HTML 导出、HAR 或通知。
- 浏览器 profile 可以保存普通站点状态，但不假定它能永久跳过 Turnstile；每天仍可能需要人工点击。
- 等待验证使用可配置超时，默认 120 秒。超时后关闭该账号并给出明确错误。
- Python 不记录、打印或持久化 Turnstile token；它只作为页面上下文内一次调用的临时值。
- 调试截图对 Tabitoken 默认禁用；即使启用调试，也只允许保存不含令牌输入值的页面截图。

## 错误处理

脚本需要区分以下错误：

- 配置文件不存在、JSON 格式错误、账号缺少 `access_token`：启动前校验失败。
- 令牌无效或过期：`GET /api/user/self` 返回未授权，记录“认证失败”，不输出响应中的令牌相关内容。
- Turnstile 超时：记录“等待人工验证超时”。
- 站点无法访问、浏览器启动失败或页面元素变化：记录具体阶段和简短错误。
- 已签到：作为成功结果，不重复点击。

退出码为：全部成功返回 `0`；存在失败账号返回 `1`；配置文件无法读取或解析返回 `2`。

## 测试验收

先写测试再实现，至少覆盖：

- 默认账号文件路径和 `TABITOKEN_ACCOUNTS_FILE` 覆盖逻辑。
- 合法账号加载；缺少令牌、空令牌、非数组 JSON 被拒绝。
- 令牌不会出现在日志格式化结果或异常摘要中。
- Tabitoken 的 URL、profile 路径、用户信息路径和签到路径固定正确。
- 已签到状态不会触发 POST；需要验证状态会进入等待分支；验证超时返回失败。
- 成功签到、已签到、认证失败、配置错误分别映射到预期结果和退出码。

真实 Turnstile 交互不放入自动化单元测试；通过一次本地手动运行验收浏览器弹出、验证等待、签到成功和窗口关闭。

## 非目标

- 不修改 AnyRouter/AgentRouter 账号格式或签到逻辑。
- 不支持 GitHub Actions 无头环境自动完成 Tabitoken 签到。
- 不实现验证码识别、第三方打码或 Turnstile 绕过。
- 不将 Tabitoken 访问令牌转换成 Cookie 或写入共享账号文件。
