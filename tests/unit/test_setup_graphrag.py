"""Pin checkout behavior using disposable local Git repositories; no network/config."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()


class SetupGraphRAGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='graphrag pin ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'upstream'
        self.remote.mkdir()
        git(self.remote, 'init', '-q')
        git(self.remote, 'config', 'user.name', 'Fixture')
        git(self.remote, 'config', 'user.email', 'fixture@example.invalid')
        (self.remote / 'content').write_text('one')
        git(self.remote, 'add', '.')
        git(self.remote, 'commit', '-qm', 'one')
        self.first = git(self.remote, 'rev-parse', 'HEAD')
        (self.remote / 'content').write_text('two')
        git(self.remote, 'commit', '-qam', 'two')
        self.second = git(self.remote, 'rev-parse', 'HEAD')
        self.pin = self.root / 'pin.txt'
        self.checkout = self.root / 'checkout'

    def run_setup(self, revision):
        self.pin.write_text(revision + '\n')
        return subprocess.run(['bash', '-c', '''set -euo pipefail
info() { printf '%s\\n' "$*"; }
success() { printf '%s\\n' "$*"; }
error() { printf '%s\\n' "$*" >&2; }
source "$1"
ensure_graphrag_checkout "$2" "$3" "$4"
''', 'fixture', str(ROOT / 'scripts/setup-graphrag.sh'), str(self.checkout), str(self.pin), str(self.remote)],
            capture_output=True, text=True, timeout=20,
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})

    def test_fresh_checkout_uses_pin_not_remote_head_and_repeat_preserves_edits(self):
        result = self.run_setup(self.first)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.first, git(self.checkout, 'rev-parse', 'HEAD'))
        self.assertEqual('3.12\n', (self.checkout / '.python-version').read_text())
        (self.checkout / 'content').write_text('local edits')
        (self.checkout / '.env').write_text('fixture config')
        result = self.run_setup(self.first)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('local edits', (self.checkout / 'content').read_text())
        self.assertEqual('fixture config', (self.checkout / '.env').read_text())

    def test_clean_update_allows_generated_python_version(self):
        self.assertEqual(0, self.run_setup(self.first).returncode)
        result = self.run_setup(self.second)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.second, git(self.checkout, 'rev-parse', 'HEAD'))
        self.assertEqual('two', (self.checkout / 'content').read_text())

    def test_dirty_different_head_is_rejected_and_preserved(self):
        self.assertEqual(0, self.run_setup(self.first).returncode)
        (self.checkout / 'content').write_text('keep me')
        result = self.run_setup(self.second)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('local changes', result.stderr)
        self.assertEqual(self.first, git(self.checkout, 'rev-parse', 'HEAD'))
        self.assertEqual('keep me', (self.checkout / 'content').read_text())

    def test_unavailable_pin_never_reports_success_or_changes_existing_head(self):
        self.assertEqual(0, self.run_setup(self.first).returncode)
        result = self.run_setup('0' * 40)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('Cannot fetch pinned', result.stderr)
        self.assertNotIn('ready at pinned', result.stdout)
        self.assertEqual(self.first, git(self.checkout, 'rev-parse', 'HEAD'))

    def test_fresh_unavailable_pin_fails(self):
        result = self.run_setup('0' * 40)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('ready at pinned', result.stdout)

    def test_ignored_configuration_is_not_overwritten_on_update(self):
        (self.remote / '.gitignore').write_text('settings.local\n')
        git(self.remote, 'add', '.gitignore')
        git(self.remote, 'commit', '-qm', 'ignore local config')
        base = git(self.remote, 'rev-parse', 'HEAD')
        (self.remote / 'settings.local').write_text('upstream config')
        git(self.remote, 'add', '-f', 'settings.local')
        git(self.remote, 'commit', '-qm', 'track config')
        target = git(self.remote, 'rev-parse', 'HEAD')
        self.assertEqual(0, self.run_setup(base).returncode)
        (self.checkout / 'settings.local').write_text('user config')
        result = self.run_setup(target)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(base, git(self.checkout, 'rev-parse', 'HEAD'))
        self.assertEqual('user config', (self.checkout / 'settings.local').read_text())

    def test_existing_non_repository_is_preserved(self):
        self.checkout.mkdir()
        (self.checkout / 'config').write_text('keep')
        result = self.run_setup(self.first)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('keep', (self.checkout / 'config').read_text())
