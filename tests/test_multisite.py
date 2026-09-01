import json
from datetime import datetime

import pytest

from multisite_checkin import (
	MULTISITE_CHECKIN_PATH,
	MULTISITE_PROFILE_PATH,
	MULTISITE_USER_PATH,
	SUPPORTED_SITES,
	MultisiteAccount,
	MultisiteAccountResult,
	MultisiteCheckinResult,
	MultisiteOutcome,
	SiteConfig,
	build_bearer_headers,
	build_site_config,
	check_in_with_page,
	classify_checkin_response,
	format_dingtalk_summary,
	is_valid_site_label,
	load_multisite_accounts,
	load_multisite_browser_settings,
	main,
	normalize_site_url,
	open_site_page,
	redact_error,
	resolve_site_config,
	run_all_multisite_accounts,
	run_multisite_account,
	send_dingtalk_summary,
)


class FakePage:
	def __init__(self, responses, *, turnstile_error=None):
		self.responses = list(responses)
		self.evaluate_calls = []
		self.wait_calls = []
		self.turnstile_error = turnstile_error

	async def evaluate(self, _script, argument):
		self.evaluate_calls.append(argument)
		return self.responses.pop(0)

	async def wait_for_function(self, _script, timeout):
		self.wait_calls.append(timeout)
		if self.turnstile_error:
			raise self.turnstile_error


class FakeDingTalk:
	def __init__(self, webhook='https://oapi.dingtalk.com/robot/send?access_token=webhook-secret', error=None):
		self.dingding_webhook = webhook
		self.error = error
		self.messages = []

	def send_dingtalk(self, title, content):
		if self.error:
			raise self.error
		self.messages.append((title, content))


def test_dingtalk_summary_includes_keyword_counts_and_account_results():
	results = [
		MultisiteAccountResult(
			account=MultisiteAccount('tabitoken', 'main', 'secret-token-1'),
			outcome=MultisiteOutcome.ALREADY_CHECKED,
		),
		MultisiteAccountResult(
			account=MultisiteAccount('justwoker', 'backup', 'secret-token-2'),
			outcome=MultisiteOutcome.AUTH_FAILED,
		),
	]

	title, content = format_dingtalk_summary(results, executed_at=datetime(2026, 8, 23, 18, 30))

	assert title == 'tabitoken 多站点签到汇总'
	assert '执行时间: 2026-08-23 18:30:00' in content
	assert '总计: 2' in content
	assert '成功: 1' in content
	assert '失败: 1' in content
	assert 'tabitoken/main: already_checked' in content
	assert 'justwoker/backup: auth_failed' in content
	assert 'secret-token' not in content


def test_send_dingtalk_summary_sends_exactly_one_message():
	notifier = FakeDingTalk()
	results = [
		MultisiteAccountResult(
			account=MultisiteAccount('gorouter', 'main', 'secret-token'),
			outcome=MultisiteOutcome.SUCCESS,
		)
	]

	send_dingtalk_summary(notifier, results, executed_at=datetime(2026, 8, 23, 18, 30))

	assert len(notifier.messages) == 1
	assert notifier.messages[0][0] == 'tabitoken 多站点签到汇总'


def test_send_dingtalk_summary_skips_missing_webhook(capsys):
	notifier = FakeDingTalk(webhook=None)

	send_dingtalk_summary(notifier, [], executed_at=datetime(2026, 8, 23, 18, 30))

	assert notifier.messages == []
	assert 'webhook not configured' in capsys.readouterr().out


def test_send_dingtalk_summary_redacts_webhook_from_failure(capsys):
	webhook = 'https://oapi.dingtalk.com/robot/send?access_token=webhook-secret'
	notifier = FakeDingTalk(webhook=webhook, error=RuntimeError(f'failed for {webhook}'))

	send_dingtalk_summary(notifier, [], executed_at=datetime(2026, 8, 23, 18, 30))

	output = capsys.readouterr().out
	assert 'DingTalk notification failed' in output
	assert webhook not in output
	assert 'webhook-secret' not in output


@pytest.mark.asyncio
async def test_run_all_accounts_sends_one_summary_and_keeps_failure_exit_code(monkeypatch):
	notifier = FakeDingTalk()
	accounts = [
		MultisiteAccount('tabitoken', 'success', 'secret-token-1'),
		MultisiteAccount('justwoker', 'failed', 'secret-token-2'),
	]

	async def fake_run(account):
		outcome = MultisiteOutcome.SUCCESS if account.name == 'success' else MultisiteOutcome.AUTH_FAILED
		return MultisiteCheckinResult(outcome)

	monkeypatch.setattr('multisite_checkin.run_multisite_account', fake_run)

	exit_code = await run_all_multisite_accounts(accounts, notifier)

	assert exit_code == 1
	assert len(notifier.messages) == 1
	assert '成功: 1' in notifier.messages[0][1]
	assert '失败: 1' in notifier.messages[0][1]


def test_main_sends_config_error_summary_and_keeps_exit_code(monkeypatch, tmp_path):
	notifier = FakeDingTalk()
	missing_file = tmp_path / 'missing.json'
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(missing_file))
	monkeypatch.setattr('multisite_checkin._create_dingtalk_notifier', lambda: notifier)

	exit_code = main()

	assert exit_code == 2
	assert len(notifier.messages) == 1
	assert '配置错误:' in notifier.messages[0][1]
	assert str(missing_file) in notifier.messages[0][1]


def test_main_sends_summary_for_empty_account_list(monkeypatch, tmp_path):
	notifier = FakeDingTalk()
	accounts_file = tmp_path / 'empty.json'
	accounts_file.write_text('[]', encoding='utf-8')
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))
	monkeypatch.setattr('multisite_checkin._create_dingtalk_notifier', lambda: notifier)

	exit_code = main()

	assert exit_code == 0
	assert len(notifier.messages) == 1
	assert '总计: 0' in notifier.messages[0][1]


def test_supported_sites_use_shared_new_api_endpoints():
	assert set(SUPPORTED_SITES) == {'tabitoken', 'gorouter', 'justwoker', 'kktoken'}
	assert SUPPORTED_SITES['tabitoken'].domain == 'https://tabitoken.com'
	assert SUPPORTED_SITES['gorouter'].domain == 'https://gorouter.app'
	assert SUPPORTED_SITES['justwoker'].domain == 'https://api.justwoker.icu'
	assert SUPPORTED_SITES['kktoken'].domain == 'https://kktoken.cc'
	assert SUPPORTED_SITES['gorouter'].api_user_header == 'New-Api-User'
	assert SUPPORTED_SITES['tabitoken'].api_user_header is None
	assert SUPPORTED_SITES['justwoker'].api_user_header is None
	for config in SUPPORTED_SITES.values():
		assert config.profile_path == MULTISITE_PROFILE_PATH
		assert config.user_path == MULTISITE_USER_PATH
		assert config.checkin_path == MULTISITE_CHECKIN_PATH


def test_load_multisite_accounts_from_default_file(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'multisite_accounts.json'
	accounts_file.write_text(
		json.dumps([{'site': 'gorouter', 'name': 'primary', 'access_token': 'secret-token', 'api_user': '12345'}]),
		encoding='utf-8',
	)
	monkeypatch.chdir(tmp_path)

	assert load_multisite_accounts() == [
		MultisiteAccount(site='gorouter', name='primary', access_token='secret-token', api_user='12345')
	]


def test_load_multisite_accounts_honors_file_override(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'custom.json'
	accounts_file.write_text(
		json.dumps([{'site': 'justwoker', 'name': 'custom', 'access_token': 'override-token'}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	assert load_multisite_accounts()[0].site == 'justwoker'


@pytest.mark.parametrize(
	'payload',
	[
		{},
		{'site': 'unknown', 'name': 'one', 'access_token': 'token'},
		{'site': 'gorouter', 'name': '', 'access_token': 'token'},
		{'site': 'gorouter', 'name': 'one', 'access_token': '   '},
		{'site': 'gorouter', 'name': 'one', 'access_token': 'token'},
	],
)
def test_load_multisite_accounts_rejects_invalid_entries(monkeypatch, tmp_path, payload):
	accounts_file = tmp_path / 'invalid.json'
	accounts_file.write_text(json.dumps([payload]), encoding='utf-8')
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError):
		load_multisite_accounts()


def test_load_multisite_accounts_rejects_non_array(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'invalid.json'
	accounts_file.write_text(json.dumps({'site': 'gorouter'}), encoding='utf-8')
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError):
		load_multisite_accounts()


def test_bearer_headers_use_access_token():
	assert build_bearer_headers('secret-token') == {
		'Authorization': 'Bearer secret-token',
		'Accept': 'application/json',
	}


@pytest.mark.asyncio
async def test_gorouter_request_headers_include_api_user():
	page = FakePage(
		[
			{'status': 200, 'payload': {'success': True}},
			{
				'status': 200,
				'payload': {'success': True, 'data': {'stats': {'checked_in_today': True}}},
			},
		]
	)

	await check_in_with_page(
		page,
		MultisiteAccount('gorouter', 'primary', 'secret-token', api_user='12345'),
		SUPPORTED_SITES['gorouter'],
	)

	assert page.evaluate_calls[0]['headers'] == {
		'Authorization': 'Bearer secret-token',
		'Accept': 'application/json',
		'New-Api-User': '12345',
	}


@pytest.mark.asyncio
async def test_non_gorouter_request_headers_do_not_include_api_user():
	page = FakePage(
		[
			{'status': 200, 'payload': {'success': True}},
			{
				'status': 200,
				'payload': {'success': True, 'data': {'stats': {'checked_in_today': True}}},
			},
		]
	)

	await check_in_with_page(
		page,
		MultisiteAccount('tabitoken', 'primary', 'secret-token', api_user='should-not-send'),
		SUPPORTED_SITES['tabitoken'],
	)

	assert page.evaluate_calls[0]['headers'] == {
		'Authorization': 'Bearer secret-token',
		'Accept': 'application/json',
	}


def test_redact_error_removes_token_from_exception_text():
	token = 'secret-token'

	assert redact_error(RuntimeError(f'failed with {token}'), token) == 'failed with [REDACTED]'


def test_browser_profile_is_isolated_by_site_and_account(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))

	settings = load_multisite_browser_settings(MultisiteAccount('gorouter', 'primary', 'token'))

	assert settings.headless is False
	assert settings.persist_profile is True
	assert settings.profile_dir == tmp_path / 'multisite' / 'gorouter' / 'primary'


def test_success_and_turnstile_messages_are_classified():
	assert classify_checkin_response(200, {'success': True}) == MultisiteOutcome.SUCCESS
	assert (
		classify_checkin_response(200, {'success': False, 'message': 'Turnstile verification required'})
		== MultisiteOutcome.NEEDS_TURNSTILE
	)
	assert (
		classify_checkin_response(401, {'success': False, 'message': 'Unauthorized, invalid access token'})
		== MultisiteOutcome.AUTH_FAILED
	)


def test_turnstile_message_takes_priority_over_forbidden_status():
	result = classify_checkin_response(
		403,
		{'success': False, 'message': 'Cloudflare Turnstile challenge required'},
	)

	assert result == MultisiteOutcome.NEEDS_TURNSTILE


@pytest.mark.asyncio
async def test_already_checked_does_not_post():
	page = FakePage(
		[
			{'status': 200, 'payload': {'success': True}},
			{
				'status': 200,
				'payload': {'success': True, 'data': {'stats': {'checked_in_today': True}}},
			},
		]
	)

	result = await check_in_with_page(
		page,
		MultisiteAccount('gorouter', 'primary', 'secret-token'),
		SUPPORTED_SITES['gorouter'],
	)

	assert result.outcome == MultisiteOutcome.ALREADY_CHECKED
	assert len(page.evaluate_calls) == 2


@pytest.mark.asyncio
async def test_invalid_access_token_stops_before_checkin():
	page = FakePage([{'status': 401, 'payload': {'success': False, 'message': 'Unauthorized'}}])

	result = await check_in_with_page(
		page,
		MultisiteAccount('justwoker', 'primary', 'secret-token'),
		SUPPORTED_SITES['justwoker'],
	)

	assert result.outcome == MultisiteOutcome.AUTH_FAILED
	assert len(page.evaluate_calls) == 1


@pytest.mark.asyncio
async def test_turnstile_timeout_returns_failure_without_logging_token(monkeypatch, capsys):
	page = FakePage(
		[{'status': 200, 'payload': {'success': False, 'message': 'Turnstile required'}}],
		turnstile_error=TimeoutError('secret-token'),
	)

	result = await check_in_with_page(
		page,
		MultisiteAccount('tabitoken', 'primary', 'secret-token'),
		SUPPORTED_SITES['tabitoken'],
		turnstile_timeout_ms=10,
	)

	assert result.outcome == MultisiteOutcome.TURNSTILE_TIMEOUT
	assert 'secret-token' not in capsys.readouterr().out


def test_preset_account_keeps_default_site_config():
	account = MultisiteAccount('kktoken', 'primary', 'token')

	assert account.site_config is None
	assert resolve_site_config(account) is SUPPORTED_SITES['kktoken']


def test_custom_site_with_url_needs_no_code_change(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'custom-site.json'
	accounts_file.write_text(
		json.dumps([{'site': 'newapi', 'url': 'https://newapi.example.com/', 'name': 'one', 'access_token': 'token'}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	account = load_multisite_accounts()[0]
	config = resolve_site_config(account)

	assert account.site == 'newapi'
	assert config.domain == 'https://newapi.example.com'
	assert config.profile_path == MULTISITE_PROFILE_PATH
	assert config.user_path == MULTISITE_USER_PATH
	assert config.checkin_path == MULTISITE_CHECKIN_PATH
	assert config.api_user_header is None


def test_custom_site_accepts_domain_key_and_path_overrides(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'overrides.json'
	accounts_file.write_text(
		json.dumps(
			[
				{
					'site': 'newapi',
					'domain': 'https://newapi.example.com:8443/prefix/',
					'name': 'one',
					'access_token': 'token',
					'profile_path': 'login',
					'user_path': '/api/self',
					'checkin_path': '/api/sign',
				}
			]
		),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	config = resolve_site_config(load_multisite_accounts()[0])

	assert config == SiteConfig(
		domain='https://newapi.example.com:8443/prefix',
		profile_path='/login',
		user_path='/api/self',
		checkin_path='/api/sign',
	)


def test_url_overrides_preset_domain_without_losing_api_user_header(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'mirror.json'
	accounts_file.write_text(
		json.dumps(
			[
				{
					'site': 'gorouter',
					'url': 'https://mirror.gorouter.app',
					'name': 'one',
					'access_token': 'token',
					'api_user': '12345',
				}
			]
		),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	config = resolve_site_config(load_multisite_accounts()[0])

	assert config.domain == 'https://mirror.gorouter.app'
	assert config.api_user_header == 'New-Api-User'


def test_custom_site_declaring_api_user_header_requires_api_user(monkeypatch, tmp_path):
	entry = {
		'site': 'newapi',
		'url': 'https://newapi.example.com',
		'name': 'one',
		'access_token': 'token',
		'api_user_header': 'New-Api-User',
	}
	accounts_file = tmp_path / 'api-user.json'
	accounts_file.write_text(json.dumps([entry]), encoding='utf-8')
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError, match='api_user'):
		load_multisite_accounts()

	accounts_file.write_text(json.dumps([{**entry, 'api_user': '42'}]), encoding='utf-8')

	account = load_multisite_accounts()[0]

	assert account.api_user == '42'
	assert (
		build_bearer_headers(
			account.access_token,
			api_user=account.api_user,
			api_user_header=resolve_site_config(account).api_user_header,
		)['New-Api-User']
		== '42'
	)


def test_unknown_site_without_url_reports_known_sites(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'unknown.json'
	accounts_file.write_text(
		json.dumps([{'site': 'newapi', 'name': 'one', 'access_token': 'token'}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError, match='kktoken'):
		load_multisite_accounts()


@pytest.mark.parametrize(
	'payload',
	[
		{'site': 'newapi', 'url': 'newapi.example.com', 'name': 'one', 'access_token': 'token'},
		{'site': 'newapi', 'url': 'ftp://newapi.example.com', 'name': 'one', 'access_token': 'token'},
		{'site': 'newapi', 'url': '   ', 'name': 'one', 'access_token': 'token'},
		{'site': '../escape', 'url': 'https://newapi.example.com', 'name': 'one', 'access_token': 'token'},
		{'site': 'a/b', 'url': 'https://newapi.example.com', 'name': 'one', 'access_token': 'token'},
	],
)
def test_load_multisite_accounts_rejects_invalid_site_definitions(monkeypatch, tmp_path, payload):
	accounts_file = tmp_path / 'invalid-site.json'
	accounts_file.write_text(json.dumps([payload]), encoding='utf-8')
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError):
		load_multisite_accounts()


def test_site_label_must_stay_path_safe():
	assert is_valid_site_label('kktoken')
	assert is_valid_site_label('自定义')
	assert not is_valid_site_label('')
	assert not is_valid_site_label('..')
	assert not is_valid_site_label('a/b')
	assert not is_valid_site_label('a\\b')


def test_normalize_site_url_keeps_scheme_host_and_subpath():
	assert normalize_site_url(' https://kktoken.cc/ ') == 'https://kktoken.cc'
	assert normalize_site_url('http://127.0.0.1:3000/newapi/') == 'http://127.0.0.1:3000/newapi'

	with pytest.raises(ValueError):
		normalize_site_url('kktoken.cc')


def test_build_site_config_returns_none_for_plain_preset_entry():
	assert build_site_config('kktoken', {'site': 'kktoken', 'name': 'one', 'access_token': 'token'}) is None


def test_resolve_site_config_rejects_unknown_site_without_config():
	with pytest.raises(ValueError, match='Unknown site'):
		resolve_site_config(MultisiteAccount('newapi', 'one', 'token'))


def test_browser_profile_isolates_custom_sites(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	account = MultisiteAccount('newapi', 'one', 'token', site_config=SiteConfig(domain='https://newapi.example.com'))

	settings = load_multisite_browser_settings(account)

	assert settings.profile_dir == tmp_path / 'multisite' / 'newapi' / 'one'


class FakeResponse:
	def __init__(self, status):
		self.status = status


class FakeNavigationPage:
	def __init__(self, result):
		self.result = result
		self.goto_calls = []

	async def goto(self, url, wait_until, timeout):
		self.goto_calls.append((url, wait_until, timeout))
		if isinstance(self.result, Exception):
			raise self.result
		return self.result


@pytest.mark.asyncio
async def test_open_site_page_accepts_successful_navigation():
	page = FakeNavigationPage(FakeResponse(200))

	assert await open_site_page(
		page,
		MultisiteAccount('kktoken', 'primary', 'token'),
		SUPPORTED_SITES['kktoken'],
		timeout_ms=1000,
	)
	assert page.goto_calls[0][0] == 'https://kktoken.cc/sign-in'


@pytest.mark.asyncio
async def test_open_site_page_reports_firewall_status(capsys):
	page = FakeNavigationPage(FakeResponse(403))

	assert not await open_site_page(
		page,
		MultisiteAccount('kktoken', 'primary', 'token'),
		SUPPORTED_SITES['kktoken'],
		timeout_ms=1000,
	)
	output = capsys.readouterr().out
	assert 'HTTP 403' in output
	assert 'CHECKIN_PROXY_URL' in output


@pytest.mark.asyncio
async def test_open_site_page_hides_token_from_navigation_error(capsys):
	page = FakeNavigationPage(TimeoutError('net::ERR_TIMED_OUT secret-token'))

	assert not await open_site_page(
		page,
		MultisiteAccount('kktoken', 'primary', 'secret-token'),
		SUPPORTED_SITES['kktoken'],
		timeout_ms=1000,
	)
	output = capsys.readouterr().out
	assert 'cannot open https://kktoken.cc/sign-in' in output
	assert 'secret-token' not in output


@pytest.mark.asyncio
async def test_unreachable_account_skips_browser_check_in(monkeypatch):
	from multisite_checkin import run_multisite_account

	class FakeContext:
		def __init__(self):
			self.closed = False

		async def new_page(self):
			return FakeNavigationPage(FakeResponse(403))

		async def close(self):
			self.closed = True

	context = FakeContext()

	async def fake_launch(_settings):
		return context

	async def fail_check_in(*_args, **_kwargs):
		raise AssertionError('check-in must not run when the site is blocked')

	monkeypatch.setattr('multisite_checkin.launch_multisite_context', fake_launch)
	monkeypatch.setattr('multisite_checkin.check_in_with_page', fail_check_in)

	result = await run_multisite_account(MultisiteAccount('kktoken', 'primary', 'token'))

	assert result.outcome == MultisiteOutcome.SITE_UNREACHABLE
	assert context.closed is True


def test_firewall_html_is_not_mistaken_for_turnstile_or_auth_failure():
	blocked = {'success': False, 'non_json': True, 'message': '<!DOCTYPE html><html class="no-js" lang="en-US">'}

	assert classify_checkin_response(403, blocked) == MultisiteOutcome.SITE_UNREACHABLE
	assert classify_checkin_response(503, blocked) == MultisiteOutcome.SITE_UNREACHABLE
	assert (
		classify_checkin_response(403, {'success': False, 'message': 'Attention Required! | Cloudflare'})
		== MultisiteOutcome.SITE_UNREACHABLE
	)
	assert (
		classify_checkin_response(200, {'success': False, 'non_json': True, 'message': '<html></html>'})
		== MultisiteOutcome.FAILED
	)
	assert (
		classify_checkin_response(403, {'success': False, 'message': 'Cloudflare Turnstile challenge required'})
		== MultisiteOutcome.NEEDS_TURNSTILE
	)


@pytest.mark.asyncio
async def test_blocked_user_endpoint_reports_site_unreachable():
	page = FakePage([{'status': 403, 'payload': {'success': False, 'non_json': True, 'message': '<html>'}}])

	result = await check_in_with_page(
		page,
		MultisiteAccount('kktoken', 'primary', 'secret-token'),
		SUPPORTED_SITES['kktoken'],
	)

	assert result.outcome == MultisiteOutcome.SITE_UNREACHABLE
	assert page.wait_calls == []


def test_browser_settings_use_proxy_when_configured(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	assert load_multisite_browser_settings(MultisiteAccount('kktoken', 'primary', 'token')).proxy == {
		'server': 'http://127.0.0.1:7890'
	}
	assert (
		load_multisite_browser_settings(MultisiteAccount('kktoken', 'primary', 'token', use_proxy=False)).proxy is None
	)


def test_browser_settings_have_no_proxy_without_env(monkeypatch, tmp_path, capsys):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)

	settings = load_multisite_browser_settings(MultisiteAccount('kktoken', 'primary', 'token', use_proxy=True))

	assert settings.proxy is None
	assert 'CHECKIN_PROXY_URL is empty' in capsys.readouterr().out


def test_account_use_proxy_is_loaded_from_config(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'proxy.json'
	accounts_file.write_text(
		json.dumps(
			[
				{'site': 'kktoken', 'name': 'proxied', 'access_token': 'token', 'use_proxy': True},
				{'site': 'kktoken', 'name': 'direct', 'access_token': 'token', 'use_proxy': False},
				{'site': 'kktoken', 'name': 'default', 'access_token': 'token'},
			]
		),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	assert [account.use_proxy for account in load_multisite_accounts()] == [True, False, None]


def test_use_proxy_must_be_boolean(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'bad-proxy.json'
	accounts_file.write_text(
		json.dumps([{'site': 'kktoken', 'name': 'one', 'access_token': 'token', 'use_proxy': 'yes'}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError, match='use_proxy'):
		load_multisite_accounts()


def test_dingtalk_summary_shows_unreachable_site():
	results = [
		MultisiteAccountResult(
			account=MultisiteAccount('kktoken', 'primary', 'secret-token'),
			outcome=MultisiteOutcome.SITE_UNREACHABLE,
		)
	]

	_, content = format_dingtalk_summary(results, executed_at=datetime(2026, 9, 1, 9, 0))

	assert 'kktoken/primary: site_unreachable' in content
	assert '失败: 1' in content


def test_kktoken_preset_is_marked_proxy_only():
	assert SUPPORTED_SITES['kktoken'].requires_proxy is True
	assert SUPPORTED_SITES['tabitoken'].requires_proxy is False
	assert SUPPORTED_SITES['gorouter'].requires_proxy is False
	assert SUPPORTED_SITES['justwoker'].requires_proxy is False


@pytest.mark.asyncio
async def test_proxy_only_site_fails_fast_without_proxy(monkeypatch, capsys):
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)

	async def fail_launch(_settings):
		raise AssertionError('the browser must not launch without the required proxy')

	monkeypatch.setattr('multisite_checkin.launch_multisite_context', fail_launch)

	result = await run_multisite_account(MultisiteAccount('kktoken', 'primary', 'secret-token'))

	assert result.outcome == MultisiteOutcome.SITE_UNREACHABLE
	output = capsys.readouterr().out
	assert 'only reachable through a proxy' in output
	assert 'CHECKIN_PROXY_URL' in output
	assert 'secret-token' not in output


@pytest.mark.asyncio
async def test_proxy_only_site_launches_browser_with_proxy(monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')
	launched = []

	class FakeContext:
		async def new_page(self):
			return FakeNavigationPage(FakeResponse(200))

		async def close(self):
			pass

	async def fake_launch(settings):
		launched.append(settings.proxy)
		return FakeContext()

	async def fake_check_in(_page, _account, _site_config, **_kwargs):
		return MultisiteCheckinResult(MultisiteOutcome.SUCCESS)

	monkeypatch.setattr('multisite_checkin.launch_multisite_context', fake_launch)
	monkeypatch.setattr('multisite_checkin.check_in_with_page', fake_check_in)

	result = await run_multisite_account(MultisiteAccount('kktoken', 'primary', 'token'))

	assert result.outcome == MultisiteOutcome.SUCCESS
	assert launched == [{'server': 'http://127.0.0.1:7890'}]


@pytest.mark.asyncio
async def test_proxy_only_site_respects_explicit_direct_account(monkeypatch, capsys):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	async def fail_launch(_settings):
		raise AssertionError('use_proxy=false must not silently fall back to the proxy')

	monkeypatch.setattr('multisite_checkin.launch_multisite_context', fail_launch)

	result = await run_multisite_account(MultisiteAccount('kktoken', 'primary', 'token', use_proxy=False))

	assert result.outcome == MultisiteOutcome.SITE_UNREACHABLE
	assert 'only reachable through a proxy' in capsys.readouterr().out


def test_custom_site_can_declare_requires_proxy(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'requires-proxy.json'
	accounts_file.write_text(
		json.dumps(
			[
				{
					'site': 'newapi',
					'url': 'https://newapi.example.com',
					'name': 'one',
					'access_token': 'token',
					'requires_proxy': True,
				}
			]
		),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	assert resolve_site_config(load_multisite_accounts()[0]).requires_proxy is True


def test_requires_proxy_must_be_boolean(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'bad-requires-proxy.json'
	accounts_file.write_text(
		json.dumps([{'site': 'kktoken', 'name': 'one', 'access_token': 'token', 'requires_proxy': 'yes'}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	with pytest.raises(ValueError, match='requires_proxy'):
		load_multisite_accounts()


def test_preset_requires_proxy_can_be_turned_off_per_account(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'kktoken-direct.json'
	accounts_file.write_text(
		json.dumps([{'site': 'kktoken', 'name': 'one', 'access_token': 'token', 'requires_proxy': False}]),
		encoding='utf-8',
	)
	monkeypatch.setenv('MULTISITE_ACCOUNTS_FILE', str(accounts_file))

	config = resolve_site_config(load_multisite_accounts()[0])

	assert config.requires_proxy is False
	assert config.domain == 'https://kktoken.cc'


def test_direct_sites_keep_direct_egress_by_default(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	assert load_multisite_browser_settings(MultisiteAccount('tabitoken', 'primary', 'token')).proxy is None
	assert load_multisite_browser_settings(MultisiteAccount('gorouter', 'primary', 'token')).proxy is None
	assert load_multisite_browser_settings(MultisiteAccount('kktoken', 'primary', 'token')).proxy == {
		'server': 'http://127.0.0.1:7890'
	}


def test_direct_site_can_opt_into_the_proxy(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	settings = load_multisite_browser_settings(MultisiteAccount('tabitoken', 'primary', 'token', use_proxy=True))

	assert settings.proxy == {'server': 'http://127.0.0.1:7890'}
