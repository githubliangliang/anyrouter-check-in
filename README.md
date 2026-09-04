# Any Router 多账号自动签到

[![GitHub Actions](https://github.com/millylee/anyrouter-check-in/workflows/PR%20Quality%20Checks/badge.svg)](https://github.com/millylee/anyrouter-check-in/actions)
[![codecov](https://codecov.io/gh/millylee/anyrouter-check-in/branch/main/graph/badge.svg)](https://codecov.io/gh/millylee/anyrouter-check-in)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/millylee/anyrouter-check-in/main.svg)](https://results.pre-commit.ci/latest/github/millylee/anyrouter-check-in/main)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/github/license/millylee/anyrouter-check-in)](LICENSE)

多平台多账号自动签到，理论上支持所有 NewAPI、OneAPI 平台，目前内置支持 Any Router 与 Agent Router，其它可根据文档进行摸索配置。

推荐搭配使用[Auo](https://github.com/millylee/auo)，支持任意 Claude Code Token 切换的工具。

**维护开源不易，如果本项目帮助到了你，请帮忙点个 Star，谢谢!**

用于 Claude Code 中转站 Any Router 网站多账号每日签到，一次 $25，限时注册即送 100 美金，[点击这里注册](https://anyrouter.top/register?aff=gSsN)。业界良心，支持 Claude Sonnet 4.5、GPT-5-Codex、Claude Code 百万上下文（使用 `/model sonnet[1m]` 开启），`gemini-2.5-pro` 模型。

## 功能特性

- ✅ 多平台（兼容 NewAPI 与 OneAPI）
- ✅ 单个/多账号自动签到
- ✅ 多种机器人通知（可选）
- ✅ 绕过 WAF 限制

## 配置文件

账号配置以仓库里的两个示例文件为准，复制成真实文件后按需删改条目即可（真实文件已在 `.gitignore` 中，不会被提交）：

| 示例文件 | 复制为 | 用途 | 运行命令 |
| --- | --- | --- | --- |
| `accounts.example.json` | `accounts.json` | AnyRouter / AgentRouter 等 provider 账号，邮箱密码或 session cookies 登录 | `uv run checkin.py` |
| `multisite_accounts.example.json` | `multisite_accounts.json` | 任意 New API 站点的访问令牌签到（本地有头浏览器） | `uv run python multisite_checkin.py` |

```bash
cp .env.example .env
cp accounts.example.json accounts.json                      # provider 签到
cp multisite_accounts.example.json multisite_accounts.json  # 多站点访问令牌签到
```

`.env.example` 里已经写好 `ANYROUTER_ACCOUNTS_FILE=accounts.json`，复制成 `.env` 即生效；多站点脚本默认就读 `multisite_accounts.json`，只有想换文件名时才需要设置 `MULTISITE_ACCOUNTS_FILE`。示例文件里出现的字段就是脚本认识的全部字段，配置前照着示例改即可，不用从零手写 JSON。

- `accounts.json` 的字段说明：[填写 accounts.json](#2-填写-accountsjson)
- `multisite_accounts.json` 的字段说明：[多站点访问令牌签到](#多站点访问令牌签到)

## 使用方法

### 1. Fork 本仓库

点击右上角的 "Fork" 按钮，将本仓库 fork 到你的账户。GitHub Actions 只跑 provider 签到（`accounts.json` / `ANYROUTER_ACCOUNTS`）；多站点访问令牌签到需要手动完成 Turnstile，只在本地运行。

### 2. 填写 accounts.json

`accounts.example.json` 预置了 3 个 `anyrouter` + 4 个 `agentrouter` 账号模板，删掉用不到的条目，再把占位文字换成真实值。每个账号长这样（可借助 [在线 Secrets 配置生成器](https://millylee.github.io/anyrouter-check-in/)）：

```json
[
  {
    "name": "anyrouter-1",
    "provider": "anyrouter",
    "email": "填写 anyrouter-1 的邮箱",
    "password": "填写 anyrouter-1 的密码",
    "cookies": {
      "session": "填写 anyrouter-1 的 session"
    },
    "api_user": "填写 anyrouter-1 的 new-api-user"
  }
]
```

推荐只留 `email` + `password`（浏览器登录后自动获取 cookies 与用户标识），用 session cookies 登录时才需要 `cookies` 和 `api_user`。

**字段说明**：

- `email` + `password`：推荐的浏览器登录方式，登录成功后会自动获取 cookies 与用户标识
- `cookies`：兼容旧版的 session cookies 登录方式
- `api_user`：session cookies 登录时用于请求头的 new-api-user 参数；邮箱密码登录可省略
- `provider` (可选)：指定使用的服务商，默认为 `anyrouter`
- `name` (可选)：自定义账号显示名称，用于通知和日志中标识账号

**默认值说明**：

- 如果未提供 `provider` 字段，默认使用 `anyrouter`（向后兼容）
- 如果未提供 `name` 字段，会使用 `Account 1`、`Account 2` 等默认名称
- `anyrouter` 与 `agentrouter` 配置已内置，无需填写

#### 获取 session 与 api_user（仅 cookies 登录需要）

通过 F12 工具，切到 Application 面板，拿到 session 的值，最好重新登录下，该值 1 个月有效期，但有可能提前失效，失效后报 401 错误，到时请再重新获取。

![获取 cookies](./assets/request-session.png)

通过 F12 工具，切到 Network 面板，可以过滤下，只要 Fetch/XHR，找到带 `New-Api-User`，这个值正常是 5 位数，如果是负数或者个位数，正常是未登录。

![获取 api_user](./assets/request-api-user.png)

### 3. 本地运行或同步到 GitHub Secret

本地运行不需要 secret，填好 `accounts.json` 直接跑（依赖安装见[本地开发环境设置](#本地开发环境设置)）：

```bash
uv run checkin.py
```

要用 GitHub Actions 定时签到，把 `accounts.json` 的**全部内容**（同一份 JSON 数组）粘贴成一个 secret：

1. 在你 fork 的仓库中，点击 "Settings" 选项卡
2. 在左侧菜单中找到 "Environments" -> "New environment"
3. 新建一个名为 `production` 的环境
4. 点击新建的 `production` 环境进入环境配置页
5. 点击 "Add environment secret" 创建 secret：
   - Name: `ANYROUTER_ACCOUNTS`
   - Value: `accounts.json` 的内容

### 4. 启用 GitHub Actions

1. 在你的仓库中，点击 "Actions" 选项卡
2. 如果提示启用 Actions，请点击启用
3. 找到 "AnyRouter 自动签到" workflow
4. 点击 "Enable workflow"

### 5. 测试运行

你可以手动触发一次签到来测试：

1. 在 "Actions" 选项卡中，点击 "AnyRouter 自动签到"
2. 点击 "Run workflow" 按钮
3. 确认运行

![运行结果](./assets/check-in.png)

## 执行时间

- 脚本每 6 小时执行一次（1. action 无法准确触发，基本延时 1~1.5h；2. 目前观测到 anyrouter 的签到是每 24h 而不是零点就可签到）
- 你也可以随时手动触发签到

## 注意事项

- 请确保每个账号的 cookies 和 API User 都是正确的
- 可以在 Actions 页面查看详细的运行日志
- 支持部分账号失败，只要有账号成功签到，整个任务就不会失败
- 报 401 错误，请重新获取 cookies，理论 1 个月失效，但有 Bug，详见 [#6](https://github.com/millylee/anyrouter-check-in/issues/6)
- 请求 200，但出现 Error 1040（08004）：Too many connections，官方数据库问题，目前已修复，但遇到几次了，详见 [#7](https://github.com/millylee/anyrouter-check-in/issues/7)

## 配置示例

`accounts.example.json` 本身就是多服务商示例（anyrouter + agentrouter 混在一个数组里），直接删条目、改值即可。下面只列它没覆盖到的写法。

### 只用 session cookies（向后兼容）

不写 `provider` 时默认 `anyrouter`，不写 `name` 时用 `Account 1`、`Account 2`：

```json
[
  {
    "cookies": {
      "session": "abc123session"
    },
    "api_user": "user123"
  }
]
```

## 自定义 Provider 配置（可选）

默认情况下，`anyrouter`、`agentrouter` 已内置配置，无需额外设置。如果你需要使用其他服务商，可以通过环境变量 `PROVIDERS` 配置：

### 基础配置（仅域名）

大多数情况下，只需提供 `domain` 即可，其他路径会自动使用默认值：

```json
{
  "customrouter": {
    "domain": "https://custom.example.com"
  }
}
```

### 完整配置（自定义路径）

如果服务商使用了不同的 API 路径、请求头或需要 WAF 绕过，可以额外指定：

```json
{
  "customrouter": {
    "domain": "https://custom.example.com",
    "login_path": "/auth/login",
    "sign_in_path": "/api/checkin",
    "user_info_path": "/api/profile",
    "api_user_key": "New-Api-User",
    "bypass_method": "waf_cookies",
    "waf_cookie_names": ["acw_tc", "cdn_sec_tc", "acw_sc__v2"]
  }
}
```

**关于 `bypass_method`**：

- 不设置或设置为 `null`：直接使用用户提供的 cookies 进行请求（适合无 WAF 保护的网站）
- 设置为 `"waf_cookies"`：使用 CloakBrowser 打开浏览器获取 WAF cookies 后再进行请求（适合有 WAF 保护的网站）

> 注：`anyrouter` 和 `agentrouter` 已内置默认配置，无需在 `PROVIDERS` 中配置

### 在 GitHub Actions 中配置

1. 进入你的仓库 Settings -> Environments -> production
2. 添加新的 secret：
   - Name: `PROVIDERS`
   - Value: 你的 provider 配置（JSON 格式）

**字段说明**：

- `domain` (必需)：服务商的域名
- `login_path` (可选)：登录页面路径，默认为 `/login`（仅在 `bypass_method` 为 `"waf_cookies"` 时使用）
- `sign_in_path` (可选)：签到 API 路径，默认为 `/api/user/sign_in`
- `user_info_path` (可选)：用户信息 API 路径，默认为 `/api/user/self`
- `api_user_key` (可选)：API 用户标识请求头名称，默认为 `new-api-user`
- `bypass_method` (可选)：WAF 绕过方法
  - `"waf_cookies"`：使用 CloakBrowser 打开浏览器获取 WAF cookies 后再执行签到
  - 不设置或 `null`：直接使用用户 cookies 执行签到（适合无 WAF 保护的网站）
- `waf_cookie_names` (可选)：绕过 WAF 所需 cookie 的名称列表，`bypass_method` 为 `waf_cookies` 时必须设置

**配置示例**（完整）：

```json
{
  "customrouter": {
    "domain": "https://custom.example.com",
    "login_path": "/auth/login",
    "sign_in_path": "/api/checkin",
    "user_info_path": "/api/profile",
    "api_user_key": "x-user-id",
    "bypass_method": "waf_cookies"
  }
}
```

**内置配置说明**：

- `anyrouter`：
  - `bypass_method: "waf_cookies"`（需要先获取 WAF cookies，然后执行签到）
  - `sign_in_path: "/api/user/sign_in"`
- `agentrouter`：
  - `bypass_method: "waf_cookies"`（需要获取 `acw_tc`）
  - `sign_in_path: null`（查询用户信息时自动签到）
  - `use_proxy: true`

**重要提示**：

- `PROVIDERS` 是可选的，不配置则使用内置的 `anyrouter` 和 `agentrouter`
- 自定义的 provider 配置会覆盖同名的默认配置

## 代理配置（可选）

内置的 `agentrouter` 默认 `use_proxy: true`。如果你的运行环境访问该平台不稳定，可以在 GitHub Actions 中配置 mihomo 订阅代理。

在仓库 Settings -> Environments -> production -> Environment secrets 中添加：

- `PROXY_SUBSCRIPTION_URL`：Clash/Mihomo 订阅链接。设置后，workflow 会运行 `scripts/setup_mihomo_proxy.sh`，启动本地代理并写入 `CHECKIN_PROXY_URL`。

本地运行时也可以直接使用已有代理：

```bash
CHECKIN_PROXY_URL=http://127.0.0.1:7890
PROVIDERS={"agentrouter":{"use_proxy":true}}
```

如果使用订阅脚本，默认会用 `https://www.google.com/generate_204` 测试代理连通性；也可以通过 `PROXY_TEST_URL` 覆盖。

## 开启通知

脚本支持多种通知方式，可以通过配置以下环境变量开启，如果 `webhook` 有要求安全设置，例如钉钉，可以在新建机器人时选择自定义关键词，填写 `AnyRouter`。

### 邮箱通知(STMP)

- `EMAIL_USER`: 发件人邮箱地址/STMP 登录地址
- `EMAIL_PASS`: 发件人邮箱密码/授权码
- `EMAIL_SENDER`: 邮件显示的发件人地址(可选，默认: EMAIL_USER)
- `CUSTOM_SMTP_SERVER`: 自定义发件人 SMTP 服务器(可选)
- `EMAIL_TO`: 收件人邮箱地址

### 钉钉机器人

- `DINGDING_WEBHOOK`: 钉钉机器人的 Webhook 地址

### 飞书机器人

- `FEISHU_WEBHOOK`: 飞书机器人的 Webhook 地址

### 企业微信机器人

- `WEIXIN_WEBHOOK`: 企业微信机器人的 Webhook 地址

### PushPlus 推送

- `PUSHPLUS_TOKEN`: PushPlus 的 Token

### Server 酱

- `SERVERPUSHKEY`: Server 酱的 SendKey

### Telegram Bot

- `TELEGRAM_BOT_TOKEN`: Telegram Bot 的 Token
- `TELEGRAM_CHAT_ID`: Telegram Chat ID

### Gotify 推送

- `GOTIFY_URL`: Gotify 服务的 URL 地址（例如: https://your-gotify-server/message）
- `GOTIFY_TOKEN`: Gotify 应用的访问令牌
- `GOTIFY_PRIORITY`: Gotify 消息优先级 (1-10, 默认为 9)

### Bark 推送

- `BARK_KEY`: Bark 应用的 Key（APP 打开时即可看到）
- `BARK_SERVER`: 自建 Bark 服务器地址 (可选，默认: https://api.day.app)

配置步骤：

1. 在仓库的 Settings -> Environments -> production -> Environment secrets 中添加上述环境变量
2. 每个通知方式都是独立的，可以只配置你需要的推送方式
3. 如果某个通知方式配置不正确或未配置，脚本会自动跳过该通知方式

## 故障排除

如果签到失败，请检查：

1. 账号配置格式是否正确
2. cookies 是否过期
3. API User 是否正确
4. 网站是否更改了签到接口
5. 查看 Actions 运行日志获取详细错误信息

## 本地开发环境设置

如果你需要在本地测试或开发，请按照以下步骤设置：

```bash
# 安装所有依赖
uv sync --dev

# 安装 CloakBrowser 浏览器
uv run python -m cloakbrowser install
# 如需使用本地浏览器，可设置 CLOAKBROWSER_BINARY_PATH=/path/to/browser

# 创建本地配置文件（字段以示例文件为准，详见上面的「配置文件」一节）
cp .env.example .env
cp accounts.example.json accounts.json
cp multisite_accounts.example.json multisite_accounts.json

# 编辑 accounts.json / multisite_accounts.json，把占位文字换成真实值
# .env 默认通过下面的配置加载账号文件：
# ANYROUTER_ACCOUNTS_FILE=accounts.json
# MULTISITE_ACCOUNTS_FILE=multisite_accounts.json
# PROVIDERS={"agentrouter":{"domain":"https://agentrouter.org"}}
# PROXY_SUBSCRIPTION_URL=https://example.com/sub?token=xxx
# CHECKIN_PROXY_URL=http://127.0.0.1:7890

# 运行签到脚本
uv run checkin.py
```

`accounts.json` 与 `multisite_accounts.json` 都已加入 `.gitignore`，不会被 Git 提交。`accounts.json` 的格式与 `ANYROUTER_ACCOUNTS` 完全相同，但可以换行并逐个维护账号。如果同时配置 `ANYROUTER_ACCOUNTS_FILE` 和 `ANYROUTER_ACCOUNTS`，脚本优先读取账号文件；文件不存在或格式错误时会停止运行，不会回退到旧环境变量。

若仍需使用单行环境变量，可删除 `ANYROUTER_ACCOUNTS_FILE`，再在 `.env` 中配置 `ANYROUTER_ACCOUNTS`。

## 测试

```bash
uv sync --dev

# 浏览器相关测试或本地登录可安装 CloakBrowser，或设置 CLOAKBROWSER_BINARY_PATH 指向本地浏览器
uv run python -m cloakbrowser install

# 运行测试
uv run pytest tests/

# 查看测试覆盖率
uv run pytest tests/ --cov=. --cov-report=html
```

## 多站点访问令牌签到

所有 New API 站点共用一个本地签到脚本和一个账号文件。首次配置：

```bash
cp multisite_accounts.example.json multisite_accounts.json
```

`multisite_accounts.example.json` 的 5 个条目正好覆盖了全部写法，删掉用不到的、改掉占位文字就能用：

| 示例条目 | 演示的写法 |
| --- | --- |
| `tabitoken-1` | 内置站点最简写法：只要 `site` + `name` + `access_token` |
| `gorouter-1` | 站点需要 `New-Api-User` 请求头，额外填 `api_user` |
| `justwoker-1` | 另一个内置站点，同最简写法 |
| `kktoken-1` | 只能走代理的站点，带 `"requires_proxy": true` |
| `自定义站点标识` | 未内置的站点：`site` 自定义标识 + `url` 指定地址 |

内置站点（`site` 直接填，无需 `url`）：`tabitoken`、`gorouter`、`justwoker`、`kktoken`。

新增站点不需要改代码，照抄示例文件最后那个条目即可：`site` 填一个自定义标识（用于日志和独立浏览器 profile 目录，不能包含 `/` 或 `\`），`url` 填站点地址。

```json
[
  {
    "site": "newapi",
    "url": "https://newapi.example.com",
    "name": "我的新站点",
    "access_token": "你的访问令牌"
  }
]
```

`url`（等价键名 `domain`）支持带端口和子路径，末尾斜杠会自动去掉。默认接口路径为 `/sign-in`、`/api/user/self`、`/api/user/checkin`；若某站点不同，可按账号覆盖 `profile_path`、`user_path`、`checkin_path`、`api_user_header`。给内置站点填 `url` 可切换到镜像域名，其余配置保持不变。

需要 `New-Api-User` 请求头的站点（内置的 GoRouter，或自定义站点填了 `api_user_header`）必须同时填写 `access_token` 和 `api_user`。`api_user` 可在登录后打开浏览器开发者工具的 Network 面板，查看站点 Fetch/XHR 请求头获取；其他站点不需要该字段。

运行多站点签到：

```bash
uv run python multisite_checkin.py
```

脚本会按账号顺序打开有头浏览器，每个站点和账号使用独立的持久化 profile。若出现 Cloudflare Turnstile，请在窗口中手动完成验证。`MULTISITE_ACCOUNTS_FILE` 可指定其它 JSON 文件；真实配置文件已加入 `.gitignore`。

多站点脚本默认只让声明了 `requires_proxy` 的站点走 `CHECKIN_PROXY_URL`，其余账号保持直连（避免出口 IP 变化触发风控）；某个账号想强制走代理可加 `"use_proxy": true`，反之加 `"use_proxy": false` 强制直连。若站点在当前网络被 Cloudflare 防火墙拦截（页面打不开、返回 HTTP 403 `Attention Required!`），脚本会输出 `[BLOCKED]` 并把结果记为 `site_unreachable`，不会再去等 Turnstile。

KKToken（`kktoken.cc`）只能通过代理访问，内置预设已标记 `requires_proxy`，示例文件的 `kktoken-1` 条目也写着 `"requires_proxy": true`：没配 `CHECKIN_PROXY_URL` 时脚本直接跳过该账号并提示，不会白开一次浏览器。自定义站点照抄这一行即可声明同样的限制；反过来，若你的网络能直连 KKToken，写 `"requires_proxy": false` 就能关掉（同时也不再默认走代理）。

配置 `DINGDING_WEBHOOK` 后，每次多站点签到结束都会发送账号结果汇总：第一行执行时间，第二行统计合并成一行，之后每个账号一行结果并带上额度（签到成功时显示签到前后的额度变化，按 New API 默认 500000 额度 = $1 折算）。

```text
tabitoken 多站点签到汇总
执行时间: 2026-09-04 18:30:00
总计: 3 | 成功: 2 | 失败: 1

tabitoken/main: success | 额度 $12.00 -> $13.00 (+$1.00)
gorouter/main: already_checked | 额度 $8.35
kktoken/main: site_unreachable
```

钉钉机器人自定义安全关键字需设置为 `tabitoken`；通知标题固定包含该关键字，消息不会包含访问令牌或 Turnstile 响应。

## 贡献指南

欢迎贡献代码！在提交 Pull Request 之前，请阅读[贡献指南](CONTRIBUTING.md)。

### 代码质量

本项目使用以下工具确保代码质量：

- **Ruff**: 代码风格检查和格式化
- **MyPy**: 静态类型检查
- **Bandit**: 安全漏洞扫描
- **Pytest**: 自动化测试
- **pre-commit**: Git 提交前自动检查

所有 Pull Request 会自动运行以下检查：

- ✅ 代码风格检查（Ruff Lint & Format）
- ✅ 类型检查（MyPy）
- ✅ 安全扫描（Bandit）
- ✅ 测试运行（Pytest）
- ✅ 测试覆盖率报告（Codecov）

### 本地开发

```bash
# 安装开发依赖
uv sync --dev

# 安装 pre-commit 钩子
uv run pre-commit install

# 运行代码检查
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run bandit -r . -c pyproject.toml

# 运行测试
uv run pytest tests/ --cov=.
```

## 免责声明

本脚本仅用于学习和研究目的，使用前请确保遵守相关网站的使用条款.
