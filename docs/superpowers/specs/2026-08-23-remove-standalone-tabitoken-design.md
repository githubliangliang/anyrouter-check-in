# 移除独立 Tabitoken 流程设计

## 目标

项目只保留 `multisite_checkin.py` 作为 Tabitoken、GoRouter 和 JustWoker 的访问令牌签到入口。移除独立 Tabitoken 脚本及其样例、测试和配置说明，避免维护两套签到流程。

## 范围

- 删除 `tabitoken_checkin.py`、`tabitoken_accounts.example.json` 和 `tests/test_tabitoken.py`。
- 删除独立 Tabitoken 流程的设计文档。
- 从 `README.md`、`.env.example` 和 `.gitignore` 中移除独立流程的入口、变量和账号文件引用。
- 从多站点设计文档中移除“保留独立入口”这类过时约束。
- 保留 `multisite_checkin.py` 中的 `tabitoken` 站点配置、访问令牌校验、人工 Turnstile 流程和相关测试。

## 本地敏感文件

如果本地存在 `tabitoken_accounts.json`，不由本次清理自动删除，以避免误删访问令牌。该文件不再作为受支持的入口；用户应迁移账号到 `multisite_accounts.json`。

## 验证

- `multisite_accounts.example.json` 仍包含 `tabitoken-1`、`gorouter-1` 和 `justwoker-1` 样例。
- 多站点测试通过，且代码库中不再有独立流程的活动引用。
- JSON、Ruff、MyPy、Bandit 和 `git diff --check` 通过。
