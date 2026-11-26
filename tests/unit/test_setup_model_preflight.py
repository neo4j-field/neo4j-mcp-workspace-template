from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('model_probe', ROOT / 'scripts/check-extraction-model.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ModelPreflightTests(unittest.IsolatedAsyncioTestCase):
    def completion(self, content):
        return AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))]))

    async def test_request_uses_runtime_parameters_and_validates_result(self):
        completion = self.completion('{"marker":"setup-ok","count":2}')
        with patch.dict('os.environ', {'EXTRACTION_MODEL': 'gpt-6-luna'}):
            await module.check_model(completion)
        params = completion.call_args.kwargs
        self.assertEqual('gpt-6-luna', params['model'])
        self.assertIs(module.ProbeResult, params['response_format'])
        self.assertEqual(['reasoning_effort'], params['allowed_openai_params'])
        self.assertEqual(0, params['num_retries'])
        self.assertEqual(30, params['timeout'])
        self.assertNotIn('temperature', params)

    async def test_empty_wrong_and_extra_output_fail(self):
        for content in ('', '{}', '{"marker":"wrong","count":2}', '{"marker":"setup-ok","count":2,"extra":1}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                await module.check_model(self.completion(content))

    def test_provider_error_does_not_expose_exception_body(self):
        with patch.object(module, 'check_model', AsyncMock(side_effect=RuntimeError('SECRET-PROVIDER-BODY'))), patch('sys.stderr') as stderr:
            self.assertEqual(1, module.main())
        rendered = ''.join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn('SECRET-PROVIDER-BODY', rendered)
        self.assertIn('EXTRACTION_MODEL', rendered)
