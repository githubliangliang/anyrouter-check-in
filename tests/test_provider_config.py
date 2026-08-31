import json

from utils.config import AppConfig, ProviderConfig, load_accounts_config


def test_accounts_config_loads_from_file(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'accounts.json'
	accounts_file.write_text(
		json.dumps(
			[
				{
					'name': 'Agent account',
					'provider': 'agentrouter',
					'cookies': {'session': 'session-value'},
					'api_user': '12345',
				}
			]
		),
		encoding='utf-8',
	)
	monkeypatch.setenv('ANYROUTER_ACCOUNTS_FILE', str(accounts_file))
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].name == 'Agent account'
	assert accounts[0].provider == 'agentrouter'


def test_accounts_file_takes_priority_over_inline_config(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'accounts.json'
	accounts_file.write_text(
		'[{"name":"from-file","cookies":{"session":"session"},"api_user":"1"}]',
		encoding='utf-8',
	)
	monkeypatch.setenv('ANYROUTER_ACCOUNTS_FILE', str(accounts_file))
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		'[{"name":"from-env","cookies":{"session":"session"},"api_user":"2"}]',
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].name == 'from-file'


def test_accounts_file_error_does_not_fall_back_to_inline_config(monkeypatch, tmp_path, capsys):
	monkeypatch.setenv('ANYROUTER_ACCOUNTS_FILE', str(tmp_path / 'missing.json'))
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		'[{"name":"from-env","cookies":{"session":"session"},"api_user":"2"}]',
	)

	accounts = load_accounts_config()

	assert accounts is None
	assert 'ANYROUTER_ACCOUNTS_FILE' in capsys.readouterr().out


def test_accounts_file_relative_path_uses_current_working_directory(monkeypatch, tmp_path):
	accounts_file = tmp_path / 'accounts.json'
	accounts_file.write_text(
		'[{"name":"relative-file","cookies":{"session":"session"},"api_user":"1"}]',
		encoding='utf-8',
	)
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv('ANYROUTER_ACCOUNTS_FILE', 'accounts.json')
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].name == 'relative-file'


def test_malformed_accounts_file_reports_file_source(monkeypatch, tmp_path, capsys):
	accounts_file = tmp_path / 'accounts.json'
	accounts_file.write_text('[invalid json', encoding='utf-8')
	monkeypatch.setenv('ANYROUTER_ACCOUNTS_FILE', str(accounts_file))
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)

	accounts = load_accounts_config()

	assert accounts is None
	assert 'ANYROUTER_ACCOUNTS_FILE' in capsys.readouterr().out


def test_accounts_config_still_loads_from_inline_environment(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS_FILE', raising=False)
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		'[{"name":"from-env","cookies":{"session":"session"},"api_user":"2"}]',
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].name == 'from-env'


def test_builtin_provider_profile_persistence_defaults(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is True
	assert config.providers['agentrouter'].persist_profile is False


def test_provider_profile_persistence_can_override_builtin(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps(
			{
				'anyrouter': {'domain': 'https://anyrouter.top', 'persist_profile': False},
				'agentrouter': {'domain': 'https://agentrouter.org', 'persist_profile': True},
			}
		),
	)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is False
	assert config.providers['agentrouter'].persist_profile is True


def test_custom_provider_profile_persistence_defaults_to_false(monkeypatch):
	monkeypatch.setenv('PROVIDERS', json.dumps({'custom': {'domain': 'https://custom.example.com'}}))

	config = AppConfig.load_from_env()

	assert config.providers['custom'].persist_profile is False


def test_provider_from_dict_inherits_profile_persistence_from_defaults():
	defaults = ProviderConfig(name='custom', domain='https://old.example.com', persist_profile=True)

	provider = ProviderConfig.from_dict(
		'custom',
		{'domain': 'https://new.example.com'},
		defaults=defaults,
	)

	assert provider.persist_profile is True
