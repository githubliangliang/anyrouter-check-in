# 多站点 GoRouter `api_user` 支持设计

## 目标

修复 GoRouter 多站点签到请求缺少 `New-Api-User` 请求头导致的 HTTP 401，同时保持 Tabitoken 和 JustWoker 的现有访问令牌流程不变。

## 配置

`MultisiteAccount` 增加可选的 `api_user` 字段。GoRouter 账号必须提供非空字符串；Tabitoken 和 JustWoker 不要求该字段。

```json
{
  "site": "gorouter",
  "name": "gorouter-1",
  "access_token": "填写 GoRouter 访问令牌",
  "api_user": "填写 GoRouter 的 New-Api-User"
}
```

真实账号文件只保存用户提供的 ID，不在日志、通知或异常摘要中输出访问令牌或完整请求头。

## 请求行为

站点预设通过 `SiteConfig` 声明是否需要 `New-Api-User`。构造页面内 API 请求头时始终发送 Bearer 令牌；仅 GoRouter 在 `api_user` 有效时追加 `New-Api-User`。所有用户信息、签到状态、签到提交和 Turnstile 重试请求复用同一组头。

## 错误处理

- GoRouter 缺少或为空 `api_user`：账号文件加载阶段报配置错误，退出码为 `2`，不会启动浏览器。
- GoRouter 返回 401：沿用 `auth_failed` 结果分类。
- 其它站点行为保持现状。

## 测试验收

- 合法 GoRouter 账号包含 `api_user` 并能加载。
- 缺少或空的 GoRouter `api_user` 被拒绝。
- GoRouter 请求头包含 `New-Api-User`，其它站点不包含该头。
- 多站点现有 Tabitoken、JustWoker 和 Turnstile 流程回归测试继续通过。
