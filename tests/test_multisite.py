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
	redact_error,
	resolve_site_config,
	run_all_multisite_accounts,
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
