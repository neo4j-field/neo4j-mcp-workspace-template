"""Read/write setup dotenv data without evaluating shell code or substitutions.

Supports assignments, optional export, comments, single/double quoted values and
multiline quotes. Dollar/backtick text stays literal; no variable interpolation.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

KEY = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")
# Export only application/provider settings; dotenv must not override setup control
# variables such as PATH, WORKSPACE_DIR, BASH_ENV or CHECK_MODEL.
ENV_PREFIXES = ('NEO4J_', 'OPENAI_', 'EXTRACTION_', 'EMBEDDING_', 'ANTHROPIC_',
                'AZURE_', 'AWS_', 'OLLAMA_', 'GEMINI_', 'GOOGLE_', 'VERTEX_',
                'COHERE_', 'MISTRAL_', 'DEEPSEEK_', 'GROQ_', 'TOGETHERAI_',
                'HUGGINGFACE_', 'DATABRICKS_', 'LITELLM_')
ENV_NAMES = {'BIGQUERY_PROJECT', 'INSTALL_DOCLING'}
SETUP_KEYS = ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD', 'NEO4J_DATABASE',
              'OPENAI_API_KEY', 'EMBEDDING_MODEL', 'EXTRACTION_MODEL')


def read_values(path: Path) -> dict[str, str]:
    values = {}
    lines = iter(enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1))
    for number, line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = KEY.fullmatch(line.strip())
        if not match:
            raise ValueError(f'Invalid dotenv assignment at line {number}; use KEY=value (shell commands are unsupported).')
        key, value = match.groups()
        if value.startswith(('"', "'")):
            quote, raw = value[0], value[1:]
            while True:
                closing = None
                escaped = False
                for pos, char in enumerate(raw):
                    if char == quote and not escaped:
                        closing = pos
                        break
                    escaped = char == '\\' and not escaped
                if closing is not None:
                    rest = raw[closing + 1:].strip()
                    if rest and not rest.startswith('#'):
                        raise ValueError(f'Unexpected text after quoted value at line {number}.')
                    value = raw[:closing]
                    escapes = {"\\\\": "\\", "\\'": "'"} if quote == "'" else {
                        '\\\\': '\\', '\\"': '"', '\\n': '\n', '\\r': '\r', '\\t': '\t'}
                    value = re.sub(r'\\[\\\'"nrt]', lambda m: escapes.get(m[0], m[0]), value)
                    break
                try:
                    _, continuation = next(lines)
                except StopIteration:
                    raise ValueError(f'Unclosed quoted value at line {number}.') from None
                raw += '\n' + continuation
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        if '\x00' in value:
            raise ValueError(f'NUL byte in value at line {number}.')
        values[key] = value
    return values


def main() -> int:
    mode, filename = sys.argv[1:]
    path = Path(filename)
    try:
        if mode == 'create':
            # Exclusive create plus owner-only mode, even with a permissive umask.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                for key in SETUP_KEYS:
                    value = os.environ.get(key, '').replace('\\', '\\\\').replace("'", "\\'")
                    stream.write(f"{key}='{value}'\n")
        else:
            values = read_values(path)
            if mode == 'export':
                for key, value in values.items():
                    if not (key in ENV_NAMES or key.startswith(ENV_PREFIXES)):
                        continue
                    sys.stdout.buffer.write(key.encode() + b'\0' + value.encode() + b'\0')
            elif mode != 'check':
                raise ValueError('Unknown dotenv operation.')
    except (OSError, ValueError) as exc:
        # Parser errors deliberately omit input values, which may be credentials.
        print(f'Cannot load setup dotenv: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
