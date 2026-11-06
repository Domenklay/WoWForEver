"""Minimal configuration from upstream .dist files; no legacy overrides or gameplay modules."""
import os
from pathlib import Path
import re
import subprocess
import sys

PREFIX = Path('/opt/trinitycore')


def write_config(path, settings):
    text = path.with_suffix(path.suffix + '.dist').read_text()
    for key, value in settings.items():
        pattern = re.compile(r'^' + re.escape(key) + r'\s*=.*$', re.M)
        line = f'{key} = {value}'
        text = pattern.sub(lambda _: line, text) if pattern.search(text) else text + '\n' + line + '\n'
    path.write_text(text)
    path.chmod(0o600)


def configuration(kind, environment):
    password = environment['DB_PASSWORD']
    # Installer generates hex secrets. Refuse characters that could alter the config grammar.
    if not re.fullmatch(r'[0-9a-f]{48}', password):
        raise ValueError('Expected the generated clean-install database credential')
    database = lambda name: f'"mysql;3306;trinity;{password};{name}"'
    settings = {'LoginDatabaseInfo': database('auth'), 'BindIP': '"0.0.0.0"',
                'LogsDir': '"/opt/trinitycore/logs"', 'Realm.CfgContentSetID': '137',
                'Realm.SuperDistrictID': '2'}
    if kind == 'bnetserver':
        settings.update({'LoginREST.ExternalAddress': 'trinity.actual.battle.net',
                         'LoginREST.LocalAddress': 'trinity.actual.battle.net',
                         'CertificatesFile': '"/opt/trinitycore/certs/forever.cert.pem"',
                         'PrivateKeyFile': '"/opt/trinitycore/certs/forever.key.pem"',
                         'Realm.AlsoAcceptBuilds': '""'})
    else:
        settings.update({'WorldDatabaseInfo': database('world'), 'CharacterDatabaseInfo': database('characters'),
                         'HotfixDatabaseInfo': database('hotfixes'), 'RealmID': '70', 'Expansion': '0',
                         'WorldServerPort': '8085', 'DataDir': '"/opt/trinitycore/data"',
                         'SourceDirectory': '"/src/TrinityCore"', 'MySQLExecutable': '"/usr/bin/mysql"',
                         'Updates.EnableDatabases': '15', 'Updates.AutoSetup': '1',
                         'Network.SkipBuildAuthKeyCheck': '1', 'Network.EnterEncryptedModeRegionGroup': '8',
                         'DBC.Locale': '8', 'mmap.enablePathFinding': '0', 'Classic.Hardcore': '0',
                         'Console.Enable': '0',
                         'Ra.Enable': '0', 'SOAP.Enabled': '1', 'SOAP.IP': '"0.0.0.0"', 'SOAP.Port': '7878',
                         'Logger.sql.sql': '5,DBErrors'})
    if environment.get('FOREVER_RELEASE_MANAGED') == '1':
        settings.update({'Updates.EnableDatabases': '0', 'Updates.AutoSetup': '0'})
    return settings


def main():
    command = sys.argv[1:] or ['worldserver']
    kind = 'worldserver' if command[0] == 'initialize' else command[0]
    if kind not in ('worldserver', 'bnetserver'):
        os.execvp(command[0], command)
    path = PREFIX / 'etc' / (kind + '.conf')
    write_config(path, configuration(kind, os.environ))
    args = [str(PREFIX / 'bin' / kind), '-c', str(path)]
    if command[0] == 'initialize':
        # Answers apply only to this fresh project's four empty databases.
        result = subprocess.run(args + ['-u'], input='yes\n' * 8, text=True)
        raise SystemExit(result.returncode)
    os.execv(args[0], args + command[1:])


if __name__ == '__main__':
    main()
