"""Dependency setup runs in disposable directories with fake uv, never real config."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVERS = ('mcp-neo4j-ingest', 'mcp-neo4j-lexical-graph', 'mcp-neo4j-entity-graph', 'mcp-neo4j-graphrag')


class SetupDependenciesTests(unittest.TestCase):
    def fixture(self, root):
        for name in SERVERS:
            (root / name).mkdir()
        (root / 'bin').mkdir()
        log = root / 'uv-calls.jsonl'
        uv = root / 'bin/uv'
        uv.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
with open(os.environ['SETUP_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[-1].endswith('check-extraction-model.py') and os.environ.get('SETUP_MODEL_FAIL'):
    print('synthetic model preflight failure', file=sys.stderr)
    sys.exit(17)
if sys.argv[1:] == ['--version']:
    print('uv fixture')
if sys.argv[1:2] == ['sync'] and os.environ.get('SETUP_TEST_FAIL') in sys.argv[1:] and os.environ.get('SETUP_TEST_FAIL'):
    sys.exit(23)
''')
        uv.chmod(0o755)
        env = {**os.environ, 'PATH': str(root / 'bin') + os.pathsep + os.defpath,
               'SETUP_TEST_LOG': str(log), 'INSTALL_DOCLING': ''}
        return env, log

    def test_full_setup_includes_docling_without_prompt_or_env_rewrite(self):
        for old_flag in ('', 'INSTALL_DOCLING=false\n'):
            with self.subTest(old_flag=old_flag), tempfile.TemporaryDirectory(prefix='setup fixture ') as directory:
                root = Path(directory)
                env, log = self.fixture(root)
                shutil.copy(ROOT / 'setup.sh', root / 'setup.sh')
                (root / 'scripts').mkdir()
                shutil.copy(ROOT / 'scripts/setup-dependencies.sh', root / 'scripts/setup-dependencies.sh')
                shutil.copy(ROOT / 'scripts/setup-env.py', root / 'scripts/setup-env.py')
                shutil.copy(ROOT / 'scripts/setup-graphrag.sh', root / 'scripts/setup-graphrag.sh')
                # Full-setup fixture has an exact pinned local Git checkout; never fetch.
                checkout = root / 'mcp-neo4j-graphrag'
                subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
                subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                                '-c', 'user.email=fixture@example.invalid', 'commit',
                                '--allow-empty', '-qm', 'fixture'], check=True)
                revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True)
                pin_dir = root / 'mcp-neo4j-proxy/src/mcp_neo4j_proxy'
                pin_dir.mkdir(parents=True)
                (pin_dir / 'graphrag_revision.txt').write_text(revision)
                fixture_env = ('NEO4J_URI=bolt://fixture.invalid:7687\nNEO4J_USERNAME=fixture\n'
                               'NEO4J_PASSWORD=fixture-only\nOPENAI_API_KEY=fixture-only\n' + old_flag)
                (root / '.env').write_text(fixture_env)
                result = subprocess.run(['bash', str(root / 'setup.sh')], input='', text=True,
                                        capture_output=True, env=env, cwd=root, timeout=20)
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                lexical = [c for c in calls if c[:3] == ['sync', '--directory', str(root / SERVERS[1])]]
                self.assertEqual([['sync', '--directory', str(root / SERVERS[1]), '--extra', 'docling']], lexical)
                self.assertNotIn('Install docling?', result.stdout)
                self.assertIn('Dependency sync elapsed times', result.stdout)
                self.assertEqual(fixture_env, (root / '.env').read_text())
                self.assertEqual(0o600, (root / '.env').stat().st_mode & 0o777)
                self.assertTrue((root / '.codex/config.toml').exists())
                # The optional provider probe fails before generating any config.
                (root / '.mcp.json').unlink()
                failed = subprocess.run(['bash', str(root / 'setup.sh'), '--check-model'],
                                        input='', text=True, capture_output=True,
                                        env={**env, 'SETUP_MODEL_FAIL': '1'}, cwd=root, timeout=20)
                self.assertEqual(17, failed.returncode, failed.stderr + failed.stdout)
                self.assertFalse((root / '.mcp.json').exists())


    def run_library(self, directory, *, failure=False, missing=False):
        root = Path(directory)
        for name in SERVERS:
            if not (missing and name == SERVERS[-1]):
                (root / name).mkdir()
        (root / SERVERS[0] / '.venv').mkdir()
        script = '''set -euo pipefail
WORKSPACE_DIR="$1"
info() { printf '%s\\n' "$*"; }
success() { printf '%s\\n' "$*"; }
warn() { printf '%s\\n' "$*"; }
error() { printf '%s\\n' "$*" >&2; }
uv() {
  SECONDS=$((SECONDS + 2))
  if [ "${FAIL_FIXTURE:-}" = true ] && [ "$1" = sync ] && [[ "$3" == */mcp-neo4j-lexical-graph ]]; then
    return 23
  fi
}
source "$2"
sync_local_servers
'''
        return subprocess.run(['bash', '-s', str(root), str(ROOT / 'scripts/setup-dependencies.sh')],
                              input=script, text=True, capture_output=True, timeout=10,
                              env={**os.environ, 'FAIL_FIXTURE': 'true' if failure else 'false'})

    def test_each_server_reports_elapsed_time_and_factual_environment_state(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_library(directory)
            self.assertEqual(0, result.returncode, result.stderr)
            for name in SERVERS:
                self.assertRegex(result.stdout, name + r' dependencies ready in [2-9][0-9]*s')
            self.assertIn('project .venv present', result.stdout)
            self.assertIn('project .venv absent', result.stdout)
            self.assertIn('cache state not inferred', result.stdout)

    def test_failure_preserves_exit_status_and_recovery_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_library(directory, failure=True)
            self.assertEqual(23, result.returncode)
            self.assertIn('dependency sync failed after', result.stderr)
            self.assertIn('--extra docling', result.stderr)
            self.assertNotIn('mcp-neo4j-entity-graph dependencies ready', result.stdout)

    def test_missing_server_is_explicitly_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_library(directory, missing=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('mcp-neo4j-graphrag directory not found, skipping', result.stdout)
