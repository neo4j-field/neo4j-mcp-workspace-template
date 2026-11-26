"""Credential setup runs only against disposable synthetic dotenv files."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/setup-env.py'
spec = importlib.util.spec_from_file_location('setup_env', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SetupEnvTests(unittest.TestCase):
    def test_shell_payloads_are_literal_and_quotes_comments_multiline_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / 'executed'
            path = root / '.env'
            path.write_text(f'''export OPENAI_API_KEY="$(touch {sentinel}) `touch {sentinel}` $HOME ${{HOME}}"
NEO4J_USERNAME=literal#fragment # comment
QUOTED=' space " quote '
MULTI="one
line"
''')
            values = module.read_values(path)
            self.assertIn('$(touch ', values['OPENAI_API_KEY'])
            self.assertIn('${HOME}', values['OPENAI_API_KEY'])
            self.assertEqual('literal#fragment', values['NEO4J_USERNAME'])
            self.assertEqual(' space " quote ', values['QUOTED'])
            self.assertEqual('one\nline', values['MULTI'])
            result = subprocess.run(['bash', '-c', '''set -euo pipefail
python3 "$1" check "$2"
while IFS= read -r -d '' key && IFS= read -r -d '' value; do export "$key=$value"; done < <(python3 "$1" export "$2")
[ "$NEO4J_USERNAME" = literal#fragment ]
''', 'fixture', str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(sentinel.exists())

    def test_creation_roundtrips_special_characters_and_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            secret = "space ' \\\n $(not-a-command) `also-literal` #fragment"
            result = subprocess.run([sys.executable, str(SCRIPT), 'create', str(path)],
                                    env={**os.environ, 'NEO4J_PASSWORD': secret}, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(secret, module.read_values(path)['NEO4J_PASSWORD'])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertNotIn(secret, result.stdout + result.stderr)
            again = subprocess.run([sys.executable, str(SCRIPT), 'create', str(path)], capture_output=True)
            self.assertNotEqual(0, again.returncode)
            self.assertEqual(secret, module.read_values(path)['NEO4J_PASSWORD'])

    def test_dotenv_cannot_override_shell_or_setup_control_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('WORKSPACE_DIR=/malicious\nPATH=/malicious\nCHECK_MODEL=true\nOPENAI_API_KEY=literal\n')
            result = subprocess.run([sys.executable, str(SCRIPT), 'export', str(path)], capture_output=True)
            self.assertEqual(0, result.returncode)
            self.assertEqual(b'OPENAI_API_KEY\0literal\0', result.stdout)

    def test_invalid_assignment_fails_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            for payload in ('bad-secret-command', "KEY='private-unclosed", 'KEY=private\x00value'):
                path.write_text(payload)
                result = subprocess.run([sys.executable, str(SCRIPT), 'check', str(path)], capture_output=True, text=True)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn(payload, result.stderr)


if __name__ == '__main__':
    unittest.main()
