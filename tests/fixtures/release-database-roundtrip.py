"""Real MySQL backup/clone/migration test. No game data, core, or user database is used."""
import gzip
import importlib.util
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import server_release_catalog as catalog

spec = importlib.util.spec_from_file_location('roundtrip_upgrade', ROOT / 'scripts/upgrade-forever-server.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
clean = upgrade.clean


def main():
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        states = []
        credential = secrets.token_hex(24)
        for prefix in ('old', 'new'):
            state = dict(project='forever-db-test-' + prefix + '-' + secrets.token_hex(6),
                         compose=str(folder / (prefix + '.private.json')))
            model = dict(name=state['project'], services=dict(mysql=dict(image='mysql:8.0',
                         environment=dict(MYSQL_ROOT_PASSWORD=credential),
                         volumes=['db:/var/lib/mysql'], healthcheck=dict(test=['CMD-SHELL',
                         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h 127.0.0.1 -uroot --silent'],
                         interval='2s', timeout='3s', retries=90))), volumes=dict(db={}))
            clean.write_private(Path(state['compose']), model)
            states.append(state)
        old, new = states
        try:
            for state in states:
                clean.compose(state, 'up', '-d', '--wait', 'mysql')
            clean.sql(old, '''
CREATE DATABASE auth; CREATE DATABASE world; CREATE DATABASE characters; CREATE DATABASE hotfixes;
CREATE TABLE auth.battlenet_accounts(id INT PRIMARY KEY); INSERT INTO auth.battlenet_accounts VALUES (1),(2);
CREATE TABLE auth.account(id INT PRIMARY KEY); INSERT INTO auth.account VALUES (3),(4);
CREATE TABLE characters.characters(guid INT PRIMARY KEY); INSERT INTO characters.characters VALUES (5),(6),(7);
CREATE TABLE auth.build_info(build INT PRIMARY KEY, majorVersion INT, minorVersion INT, bugfixVersion INT, hotfixVersion CHAR(1));
INSERT INTO auth.build_info VALUES (70658,1,60,1,NULL);
CREATE TABLE auth.realmlist(id INT PRIMARY KEY, gamebuild INT, contentSetId INT, flag INT);
INSERT INTO auth.realmlist VALUES (70,70658,137,0);
CREATE TABLE world.fixture(id INT PRIMARY KEY, payload LONGBLOB);
INSERT INTO world.fixture VALUES (8,0x00ff0100), (9,0xd098d0b2d0b0d0bd);
CREATE TABLE hotfixes.fixture(id INT PRIMARY KEY); INSERT INTO hotfixes.fixture VALUES (10);
''')
            baseline = upgrade.snapshot(old)
            backup = folder / 'before.sql.gz'
            sha = upgrade.dump_databases(old, backup)
            with gzip.open(backup, 'rb') as stream:
                assert b'CREATE TABLE' in stream.read()
            upgrade.restore_databases(new, backup, sha)
            assert upgrade.snapshot(new) == baseline
            assert clean.sql(new, 'SELECT HEX(payload) FROM world.fixture ORDER BY id;') == clean.sql(old, 'SELECT HEX(payload) FROM world.fixture ORDER BY id;')
            # Exercise a repository-owned, checksummed future DB migration on the clone.
            migrations = folder / 'releases/migrations'
            migrations.mkdir(parents=True)
            path = migrations / 'fixture-v2.sql'
            path.write_text('ALTER TABLE fixture ADD release_tag INT NOT NULL DEFAULT 2;\n')
            with patch.object(catalog, 'ROOT', folder):
                sql = catalog.migration_body(dict(database='world', file='fixture-v2.sql', sha256=clean.sha_file(path)))
            clean.sql(new, 'USE world;\n' + sql)
            clean.sql(new, 'INSERT INTO auth.build_info VALUES (70707,1,60,1,NULL); UPDATE auth.realmlist SET gamebuild=70707 WHERE id=70;')
            assert upgrade.snapshot(new)['counts'] == baseline['counts']
            assert upgrade.snapshot(new)['schema_sha256'] != baseline['schema_sha256']
            assert upgrade.snapshot(old) == baseline
            assert clean.sql(old, 'SELECT gamebuild FROM auth.realmlist WHERE id=70;').strip() == '70658'
            assert clean.sql(new, 'SELECT gamebuild FROM auth.realmlist WHERE id=70;').strip() == '70707'
            # Progress after cutover is retained in a second verified snapshot.
            clean.sql(new, 'INSERT INTO characters.characters VALUES (11);')
            after = folder / 'after.sql.gz'
            upgrade.dump_databases(new, after)
            assert upgrade.snapshot(new)['counts'] == ['2', '2', '4']
            assert upgrade.snapshot(old)['counts'] == ['2', '2', '3']
            print('REAL MYSQL PASS: four DBs, binary payloads, schema/count preservation, isolated migration, old build retained and post-cutover backup.')
        finally:
            for state in states:
                clean.compose(state, 'down', '--volumes')  # Only these random fixture projects.


if __name__ == '__main__':
    main()
