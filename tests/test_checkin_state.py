import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import checkin
from checkin import format_check_in_notification, generate_balance_hash, parse_cookies


def test_parse_cookies_keeps_standard_session_mapping():
	assert parse_cookies({'session': 'abc123'}) == {'session': 'abc123'}


def test_parse_cookies_extracts_session_without_stale_sibling_cookies():
	cookies = {'session': 'session=abc123; acw_tc=stale-waf-value', 'theme': 'dark'}

	assert parse_cookies(cookies) == {'session': 'abc123', 'theme': 'dark'}


def test_parse_cookies_still_accepts_raw_cookie_header():
	assert parse_cookies('session=abc123; theme=dark') == {'session': 'abc123', 'theme': 'dark'}


def test_balance_hash_changes_when_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 125.0, 'used': 20.0}}

	assert generate_balance_hash(before) != generate_balance_hash(after)


def test_balance_hash_changes_when_used_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 100.0, 'used': 21.0}}

	assert generate_balance_hash(before) != generate_balance_hash(after)


def test_balance_hash_is_stable_for_equivalent_balances():
	left = {
		'account_2': {'quota': 50.0, 'used': 1.0},
		'account_1': {'quota': 100.0, 'used': 20.0},
	}
	right = {
		'account_1': {'used': 20.0, 'quota': 100.0},
		'account_2': {'used': 1.0, 'quota': 50.0},
	}

	assert generate_balance_hash(left) == generate_balance_hash(right)


def test_check_in_notification_compacts_reward_details_without_usage():
	detail = {
		'name': '账号1',
		'before_quota': 12.0,
		'before_used': 3.0,
		'after_quota': 13.5,
		'after_used': 3.5,
		'check_in_reward': 1.5,
		'usage_increase': 0.5,
		'balance_change': 1.5,
	}

	assert format_check_in_notification(detail) == '账号1 | 余额 $12.00 -> $13.50 | 签到 +$1.50'
	assert '消耗' not in format_check_in_notification(detail)


def test_check_in_notification_shows_checked_in_for_zero_reward():
	detail = {
		'name': '账号2',
		'before_quota': 8.0,
		'before_used': 2.0,
		'after_quota': 8.0,
		'after_used': 2.5,
		'check_in_reward': 0.0,
		'usage_increase': 0.5,
		'balance_change': 0.0,
	}

	assert format_check_in_notification(detail) == '账号2 | 余额 $8.00 -> $8.00 | 已签到'
	assert '消耗' not in format_check_in_notification(detail)


@pytest.mark.asyncio
async def test_main_sends_compact_notification_without_blank_sections(monkeypatch):
	class FakeAccount:
		provider = 'anyrouter'

		def get_display_name(self, _index):
			return '账号1'

	async def fake_check_in_account(_account, _index, _app_config):
		return (
			True,
			{'success': True, 'quota': 12.0, 'used_quota': 3.0},
			{'success': True, 'quota': 13.5, 'used_quota': 3.0},
		)

	messages = []
	monkeypatch.setattr(checkin.AppConfig, 'load_from_env', lambda: SimpleNamespace(providers={}))
	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: [FakeAccount()])
	monkeypatch.setattr(checkin, 'check_in_account', fake_check_in_account)
	monkeypatch.setattr(checkin, 'load_balance_hash', lambda: None)
	monkeypatch.setattr(checkin, 'save_balance_hash', lambda _value: None)
	monkeypatch.setattr(checkin, 'is_debug_enabled', lambda: False)
	monkeypatch.setattr(
		checkin.notify, 'push_message', lambda title, content, **_kwargs: messages.append((title, content))
	)

	with pytest.raises(SystemExit) as exit_info:
		await checkin.main()

	assert exit_info.value.code == 0
	assert len(messages) == 1
	title, content = messages[0]
	assert title == 'AnyRouter Check-in Alert'
	assert '\n\n' not in content
	assert content.splitlines()[1] == '账号1 | 余额 $12.00 -> $13.50 | 签到 +$1.50'
	assert content.splitlines()[-1] == '[SUCCESS] 1/1 | [FAIL] 0/1'


@pytest.mark.asyncio
async def test_main_compacts_multiline_failure_reason(monkeypatch):
	class FakeAccount:
		provider = 'anyrouter'

		def get_display_name(self, _index):
			return '失败账号'

	async def fake_check_in_account(_account, _index, _app_config):
		return False, None, {'success': False, 'error': '认证失败\n请更新配置'}

	messages = []
	monkeypatch.setattr(checkin.AppConfig, 'load_from_env', lambda: SimpleNamespace(providers={}))
	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: [FakeAccount()])
	monkeypatch.setattr(checkin, 'check_in_account', fake_check_in_account)
	monkeypatch.setattr(checkin, 'load_balance_hash', lambda: None)
	monkeypatch.setattr(checkin, 'is_debug_enabled', lambda: False)
	monkeypatch.setattr(
		checkin.notify, 'push_message', lambda title, content, **_kwargs: messages.append((title, content))
	)

	with pytest.raises(SystemExit) as exit_info:
		await checkin.main()

	assert exit_info.value.code == 1
	assert messages[0][1].splitlines()[1] == '[FAIL] 失败账号 | 认证失败 请更新配置'


@pytest.mark.asyncio
async def test_main_appends_screenshot_hint_without_blank_line(monkeypatch):
	class FakeAccount:
		provider = 'anyrouter'

		def get_display_name(self, _index):
			return '账号1'

	async def fake_check_in_account(_account, _index, _app_config):
		return (
			True,
			{'success': True, 'quota': 12.0, 'used_quota': 3.0},
			{'success': True, 'quota': 13.5, 'used_quota': 3.0},
		)

	messages = []
	monkeypatch.setattr(checkin.AppConfig, 'load_from_env', lambda: SimpleNamespace(providers={}))
	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: [FakeAccount()])
	monkeypatch.setattr(checkin, 'check_in_account', fake_check_in_account)
	monkeypatch.setattr(checkin, 'load_balance_hash', lambda: None)
	monkeypatch.setattr(checkin, 'save_balance_hash', lambda _value: None)
	monkeypatch.setattr(checkin, 'is_debug_enabled', lambda: True)
	monkeypatch.setattr(checkin, 'take_pending_screenshots', lambda: [Path('checkin_screenshots/debug.png')])
	monkeypatch.setattr(
		checkin.notify, 'push_message', lambda title, content, **_kwargs: messages.append((title, content))
	)
	monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
	monkeypatch.delenv('GITHUB_REPOSITORY', raising=False)

	with pytest.raises(SystemExit):
		await checkin.main()

	content = messages[0][1]
	assert '\n\n' not in content
	assert content.splitlines()[-1] == '[SCREENSHOT] 1 debug screenshot(s) saved to `checkin_screenshots/`'
