#!/usr/bin/env python3
"""Local multi-site access-token check-in with manual Turnstile handling."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from dotenv import load_dotenv

from utils.proxy import get_playwright_proxy

MULTISITE_PROFILE_PATH = '/sign-in'
MULTISITE_USER_PATH = '/api/user/self'
MULTISITE_CHECKIN_PATH = '/api/user/checkin'


@dataclass(frozen=True)
class SiteConfig:
	domain: str
	profile_path: str = MULTISITE_PROFILE_PATH
	user_path: str = MULTISITE_USER_PATH
	checkin_path: str = MULTISITE_CHECKIN_PATH
	api_user_header: str | None = None
	requires_proxy: bool = False


SUPPORTED_SITES = {
	'tabitoken': SiteConfig(domain='https://tabitoken.com'),
	'gorouter': SiteConfig(domain='https://gorouter.app', api_user_header='New-Api-User'),
	'justwoker': SiteConfig(domain='https://api.justwoker.icu'),
	'kktoken': SiteConfig(domain='https://kktoken.cc', requires_proxy=True),
}

SITE_CONFIG_OVERRIDE_KEYS = ('profile_path', 'user_path', 'checkin_path', 'api_user_header')
BLOCK_KEYWORDS = ('attention required', 'you have been blocked', 'access denied', 'error code: 1020')


@dataclass(frozen=True)
class MultisiteAccount:
	site: str
	name: str
	access_token: str
	api_user: str | None = None
	site_config: SiteConfig | None = None
	use_proxy: bool | None = None


class MultisiteOutcome(Enum):
	SUCCESS = 'success'
	ALREADY_CHECKED = 'already_checked'
	NEEDS_TURNSTILE = 'needs_turnstile'
	AUTH_FAILED = 'auth_failed'
	SITE_UNREACHABLE = 'site_unreachable'
	TURNSTILE_TIMEOUT = 'turnstile_timeout'
	FAILED = 'failed'


@dataclass(frozen=True)
class MultisiteBrowserSettings:
	headless: bool
	persist_profile: bool
	profile_dir: Path
	proxy: dict[str, str] | None = None


@dataclass(frozen=True)
class MultisiteCheckinResult:
	outcome: MultisiteOutcome


@dataclass(frozen=True)
class MultisiteAccountResult:
	account: MultisiteAccount
	outcome: MultisiteOutcome


class DingTalkNotifier(Protocol):
	dingding_webhook: str | None

	def send_dingtalk(self, title: str, content: str) -> None: ...


def format_dingtalk_summary(
	results: list[MultisiteAccountResult],
	*,
	executed_at: datetime,
	config_error: str | None = None,
) -> tuple[str, str]:
	successes = sum(
		result.outcome in {MultisiteOutcome.SUCCESS, MultisiteOutcome.ALREADY_CHECKED} for result in results
	)
	lines = [
		f'执行时间: {executed_at.strftime("%Y-%m-%d %H:%M:%S")}',
		f'总计: {len(results)}',
		f'成功: {successes}',
		f'失败: {len(results) - successes}',
	]
	if results:
		lines.append('')
		lines.extend(f'{result.account.site}/{result.account.name}: {result.outcome.value}' for result in results)
	if config_error:
		lines.extend(['', f'配置错误: {config_error}'])
	return 'tabitoken 多站点签到汇总', '\n'.join(lines)


def send_dingtalk_summary(
	notifier: DingTalkNotifier,
	results: list[MultisiteAccountResult],
	*,
	executed_at: datetime,
	config_error: str | None = None,
) -> None:
	if not notifier.dingding_webhook:
		print('[NOTIFY] DingTalk notification skipped: webhook not configured')
		return
	title, content = format_dingtalk_summary(results, executed_at=executed_at, config_error=config_error)
	try:
		notifier.send_dingtalk(title, content)
	except Exception as error:
		print(f'[NOTIFY] DingTalk notification failed: {type(error).__name__}')
		return
	print('[NOTIFY] DingTalk summary sent')


def _create_dingtalk_notifier() -> DingTalkNotifier:
	from utils.notify import NotificationKit

	return NotificationKit()


def is_valid_site_label(label: str) -> bool:
	"""Site labels double as browser-profile directory names, so keep them path-safe."""
	return bool(label) and label not in {'.', '..'} and not any(char in label for char in '/\\')


def normalize_site_url(raw: str) -> str:
	parsed = urlparse(raw.strip())
	if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
		raise ValueError(f'Invalid site url: {raw.strip()!r} (expected e.g. https://kktoken.cc)')
	return f'{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip("/")}'


def _optional_str(item: dict, key: str, index: int) -> str | None:
	value = item.get(key)
	if value is None:
		return None
	if not isinstance(value, str) or not value.strip():
		raise ValueError(f'Multisite account {index} has an empty {key}')
	return value.strip()


def _optional_bool(item: dict, key: str, index: int) -> bool | None:
	value = item.get(key)
	if value is None:
		return None
	if not isinstance(value, bool):
		raise ValueError(f'Multisite account {index} requires {key} to be true or false')
	return value


def build_site_config(site: str, item: dict, *, index: int = 1) -> SiteConfig | None:
	"""Return a per-account SiteConfig, or None when the built-in preset is enough."""
	url = _optional_str(item, 'url', index) or _optional_str(item, 'domain', index)
	overrides: dict[str, Any] = {}
	for key in SITE_CONFIG_OVERRIDE_KEYS:
		value = _optional_str(item, key, index)
		if value is None:
			continue
		overrides[key] = value if key == 'api_user_header' or value.startswith('/') else f'/{value}'
	requires_proxy = _optional_bool(item, 'requires_proxy', index)
	if requires_proxy is not None:
		overrides['requires_proxy'] = requires_proxy
	preset = SUPPORTED_SITES.get(site)
	if url is None:
		if preset is None:
			known = ', '.join(sorted(SUPPORTED_SITES))
			raise ValueError(
				f'Multisite account {index} uses unknown site "{site}", so it requires a url (known sites: {known})'
			)
		if not overrides:
			return None
	if url is not None:
		overrides['domain'] = normalize_site_url(url)
	return replace(preset or SiteConfig(domain=''), **overrides)


def resolve_site_config(account: MultisiteAccount) -> SiteConfig:
	if account.site_config is not None:
		return account.site_config
	config = SUPPORTED_SITES.get(account.site)
	if config is None:
		known = ', '.join(sorted(SUPPORTED_SITES))
		raise ValueError(f'Unknown site "{account.site}" without a url (known sites: {known})')
	return config


def load_multisite_accounts() -> list[MultisiteAccount]:
	accounts_path = Path(os.getenv('MULTISITE_ACCOUNTS_FILE', 'multisite_accounts.json'))
	try:
		payload = json.loads(accounts_path.read_text(encoding='utf-8'))
	except OSError as error:
		raise ValueError(f'Cannot read multisite accounts file: {accounts_path}') from error
	except json.JSONDecodeError as error:
		raise ValueError(f'Invalid JSON in multisite accounts file: {accounts_path}') from error

	if not isinstance(payload, list):
		raise ValueError('Multisite accounts configuration must be a JSON array')

	accounts = []
	for index, item in enumerate(payload, start=1):
		if not isinstance(item, dict):
			raise ValueError(f'Multisite account {index} must be an object')
		site = item.get('site')
		name = item.get('name')
		access_token = item.get('access_token')
		if not isinstance(site, str) or not is_valid_site_label(site.strip()):
			raise ValueError(f'Multisite account {index} requires a site label such as "kktoken"')
		if not isinstance(name, str) or not name.strip():
			raise ValueError(f'Multisite account {index} requires a non-empty name')
		if not isinstance(access_token, str) or not access_token.strip():
			raise ValueError(f'Multisite account {index} requires a non-empty access_token')
		site_name = site.strip()
		use_proxy = item.get('use_proxy')
		if use_proxy is not None and not isinstance(use_proxy, bool):
			raise ValueError(f'Multisite account {index} requires use_proxy to be true or false')
		site_config = build_site_config(site_name, item, index=index)
		api_user = item.get('api_user')
		expects_api_user = (site_config or SUPPORTED_SITES[site_name]).api_user_header is not None
		if expects_api_user and (not isinstance(api_user, str) or not api_user.strip()):
			raise ValueError(f'Multisite account {index} requires a non-empty api_user for {site_name}')
		accounts.append(
			MultisiteAccount(
				site=site_name,
				name=name.strip(),
				access_token=access_token.strip(),
				api_user=api_user.strip() if isinstance(api_user, str) else None,
				site_config=site_config,
				use_proxy=use_proxy,
			)
		)
	return accounts


def build_bearer_headers(
	access_token: str,
	*,
	api_user: str | None = None,
	api_user_header: str | None = None,
) -> dict[str, str]:
	headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}
	if api_user and api_user_header:
		headers[api_user_header] = api_user
	return headers


def redact_error(error: Exception, access_token: str) -> str:
	message = str(error)
	return message.replace(access_token, '[REDACTED]') if access_token else message


def _looks_blocked(status_code: int, payload: dict, message: str) -> bool:
	if any(keyword in message for keyword in BLOCK_KEYWORDS):
		return True
	return bool(payload.get('non_json')) and status_code in {403, 429, 503}


def classify_checkin_response(status_code: int, payload: object) -> MultisiteOutcome:
	if not isinstance(payload, dict):
		return MultisiteOutcome.FAILED
	if payload.get('success') is True:
		return MultisiteOutcome.SUCCESS

	message = str(payload.get('message', '')).lower()
	code = str(payload.get('code', '')).lower()
	if _looks_blocked(status_code, payload, message):
		return MultisiteOutcome.SITE_UNREACHABLE
	if any(keyword in message for keyword in ('turnstile', 'verify you are human', 'cloudflare', 'challenge')):
		return MultisiteOutcome.NEEDS_TURNSTILE
	if status_code in {401, 403} or 'unauthorized' in message or code == 'auth_unauthorized':
		return MultisiteOutcome.AUTH_FAILED
	if any(keyword in message for keyword in ('already checked', 'already signed', '已签到', '已经签到', '重复签到')):
		return MultisiteOutcome.ALREADY_CHECKED
	return MultisiteOutcome.FAILED


def load_multisite_browser_settings(account: MultisiteAccount) -> MultisiteBrowserSettings:
	profile_base = Path(os.getenv('CHECKIN_BROWSER_PROFILE_DIR', '.browser_profiles'))
	# Only proxy-only sites go through the proxy by default; the rest keep their direct egress.
	use_proxy = resolve_site_config(account).requires_proxy if account.use_proxy is None else account.use_proxy
	proxy = get_playwright_proxy(use_proxy=use_proxy)
	if proxy is None and account.use_proxy:
		print(f'[WARN] {account.site}/{account.name}: use_proxy is set but CHECKIN_PROXY_URL is empty')
	return MultisiteBrowserSettings(
		headless=False,
		persist_profile=True,
		profile_dir=profile_base / 'multisite' / account.site / account.name,
		proxy=proxy,
	)


def _env_bool(name: str, default: bool) -> bool:
	raw = os.getenv(name)
	if raw is None:
		return default
	return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


_PAGE_REQUEST_JS = """
async ({path, method, headers, use_turnstile}) => {
  let requestPath = path;
  if (use_turnstile) {
    const input = document.querySelector('input[name="cf-turnstile-response"]');
    const response = input?.value || '';
    if (!response) return {status: 428, payload: {success: false, message: 'Turnstile response is empty'}};
    requestPath = `${path}?turnstile=${encodeURIComponent(response)}`;
  }
  const response = await fetch(requestPath, {method, headers});
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); }
  catch { payload = {success: false, non_json: true, message: text.slice(0, 300)}; }
  return {status: response.status, payload};
}
"""

_TURNSTILE_READY_JS = """
() => Boolean(document.querySelector('input[name="cf-turnstile-response"]')?.value)
"""


async def _page_request(
	page,
	account: MultisiteAccount,
	path: str,
	site_config: SiteConfig,
	*,
	method: str = 'GET',
	use_turnstile: bool = False,
):
	return await page.evaluate(
		_PAGE_REQUEST_JS,
		{
			'path': path,
			'method': method,
			'headers': build_bearer_headers(
				account.access_token,
				api_user=account.api_user,
				api_user_header=site_config.api_user_header,
			),
			'use_turnstile': use_turnstile,
		},
	)


def _is_authenticated_user_response(response: object) -> bool:
	return (
		isinstance(response, dict)
		and isinstance(response.get('payload'), dict)
		and response['payload'].get('success') is True
	)


def _is_checked_in(response: object) -> bool:
	if not isinstance(response, dict):
		return False
	payload = response.get('payload')
	if not isinstance(payload, dict):
		return False
	data = payload.get('data')
	stats = data.get('stats') if isinstance(data, dict) else None
	return isinstance(stats, dict) and stats.get('checked_in_today') is True


async def _wait_for_turnstile(page, account: MultisiteAccount, timeout_ms: int) -> bool:
	print(f'[ACTION] {account.site}/{account.name}: Complete the Turnstile check in the browser window.')
	try:
		await page.wait_for_function(_TURNSTILE_READY_JS, timeout=timeout_ms)
	except Exception:
		return False
	return True


async def check_in_with_page(
	page,
	account: MultisiteAccount,
	site_config: SiteConfig,
	*,
	turnstile_timeout_ms: int = 120_000,
) -> MultisiteCheckinResult:
	user_response = await _page_request(page, account, site_config.user_path, site_config)
	user_outcome = classify_checkin_response(user_response.get('status', 0), user_response.get('payload'))
	if user_outcome == MultisiteOutcome.SITE_UNREACHABLE:
		return MultisiteCheckinResult(MultisiteOutcome.SITE_UNREACHABLE)
	if user_outcome == MultisiteOutcome.NEEDS_TURNSTILE:
		if not await _wait_for_turnstile(page, account, turnstile_timeout_ms):
			return MultisiteCheckinResult(MultisiteOutcome.TURNSTILE_TIMEOUT)
		user_response = await _page_request(page, account, site_config.user_path, site_config)
	if not _is_authenticated_user_response(user_response):
		return MultisiteCheckinResult(MultisiteOutcome.AUTH_FAILED)

	month = datetime.now().strftime('%Y-%m')
	status_response = await _page_request(page, account, f'{site_config.checkin_path}?month={month}', site_config)
	if _is_checked_in(status_response):
		return MultisiteCheckinResult(MultisiteOutcome.ALREADY_CHECKED)

	checkin_response = await _page_request(page, account, site_config.checkin_path, site_config, method='POST')
	outcome = classify_checkin_response(checkin_response.get('status', 0), checkin_response.get('payload'))
	if outcome == MultisiteOutcome.NEEDS_TURNSTILE:
		if not await _wait_for_turnstile(page, account, turnstile_timeout_ms):
			return MultisiteCheckinResult(MultisiteOutcome.TURNSTILE_TIMEOUT)
		checkin_response = await _page_request(
			page,
			account,
			site_config.checkin_path,
			site_config,
			method='POST',
			use_turnstile=True,
		)
		outcome = classify_checkin_response(checkin_response.get('status', 0), checkin_response.get('payload'))

	if outcome == MultisiteOutcome.ALREADY_CHECKED:
		return MultisiteCheckinResult(MultisiteOutcome.ALREADY_CHECKED)
	if outcome != MultisiteOutcome.SUCCESS:
		return MultisiteCheckinResult(outcome)

	confirmation = await _page_request(page, account, f'{site_config.checkin_path}?month={month}', site_config)
	if _is_checked_in(confirmation):
		return MultisiteCheckinResult(MultisiteOutcome.SUCCESS)
	return MultisiteCheckinResult(MultisiteOutcome.FAILED)


async def launch_multisite_context(settings: MultisiteBrowserSettings):
	from cloakbrowser import launch_persistent_context_async

	settings.profile_dir.mkdir(parents=True, exist_ok=True)
	launch_kwargs: dict = {
		'headless': settings.headless,
		'viewport': {'width': 1280, 'height': 900},
	}
	if settings.proxy:
		launch_kwargs['proxy'] = settings.proxy
		print('[INFO] Browser proxy enabled')
	if _env_bool('CHECKIN_HUMANIZE', True):
		launch_kwargs['humanize'] = True
		launch_kwargs['human_preset'] = 'careful'
	return await launch_persistent_context_async(str(settings.profile_dir), **launch_kwargs)


async def open_site_page(page, account: MultisiteAccount, site_config: SiteConfig, *, timeout_ms: int) -> bool:
	url = f'{site_config.domain}{site_config.profile_path}'
	try:
		response = await page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
	except Exception as error:
		print(
			f'[BLOCKED] {account.site}/{account.name}: cannot open {url}: {redact_error(error, account.access_token)[:200]}'
		)
		return False
	status = response.status if response is not None else 0
	if response is None or status >= 400:
		detail = f'HTTP {status}' if response is not None else 'no response'
		print(
			f'[BLOCKED] {account.site}/{account.name}: {url} returned {detail}; '
			'the site may block this network (try CHECKIN_PROXY_URL)'
		)
		return False
	return True


async def run_multisite_account(account: MultisiteAccount) -> MultisiteCheckinResult:
	site_config = resolve_site_config(account)
	settings = load_multisite_browser_settings(account)
	if site_config.requires_proxy and settings.proxy is None:
		print(
			f'[BLOCKED] {account.site}/{account.name}: this site is only reachable through a proxy; '
			'set CHECKIN_PROXY_URL (and keep the account use_proxy unset or true)'
		)
		return MultisiteCheckinResult(MultisiteOutcome.SITE_UNREACHABLE)
	page_timeout_ms = int(os.getenv('MULTISITE_PAGE_TIMEOUT_MS', '60000'))
	turnstile_timeout_ms = int(os.getenv('MULTISITE_TURNSTILE_TIMEOUT_MS', '120000'))
	context = None
	try:
		context = await launch_multisite_context(settings)
		page = await context.new_page()
		if not await open_site_page(page, account, site_config, timeout_ms=page_timeout_ms):
			return MultisiteCheckinResult(MultisiteOutcome.SITE_UNREACHABLE)
		return await check_in_with_page(
			page,
			account,
			site_config,
			turnstile_timeout_ms=turnstile_timeout_ms,
		)
	except Exception as error:
		print(f'[FAILED] {account.site}/{account.name}: {redact_error(error, account.access_token)[:200]}')
		return MultisiteCheckinResult(MultisiteOutcome.FAILED)
	finally:
		if context is not None:
			await context.close()


async def run_all_multisite_accounts(accounts: list[MultisiteAccount], notifier: DingTalkNotifier) -> int:
	successes = 0
	results = []
	for account in accounts:
		label = f'{account.site}/{account.name}'
		print(f'[PROCESSING] Starting {label}')
		result = await run_multisite_account(account)
		results.append(MultisiteAccountResult(account=account, outcome=result.outcome))
		if result.outcome in {MultisiteOutcome.SUCCESS, MultisiteOutcome.ALREADY_CHECKED}:
			successes += 1
			print(f'[SUCCESS] {label}: {result.outcome.value}')
		else:
			print(f'[FAILED] {label}: {result.outcome.value}')
	print(f'[STATS] Multisite check-in result: {successes}/{len(accounts)} succeeded')
	send_dingtalk_summary(notifier, results, executed_at=datetime.now())
	return 0 if successes == len(accounts) else 1


def main() -> int:
	load_dotenv()
	notifier = _create_dingtalk_notifier()
	try:
		accounts = load_multisite_accounts()
	except ValueError as error:
		print(f'[CONFIG] {error}')
		send_dingtalk_summary(notifier, [], executed_at=datetime.now(), config_error=str(error))
		return 2
	if not accounts:
		print('[CONFIG] No multisite accounts configured')
		send_dingtalk_summary(notifier, [], executed_at=datetime.now())
		return 0
	return asyncio.run(run_all_multisite_accounts(accounts, notifier))


if __name__ == '__main__':
	raise SystemExit(main())
