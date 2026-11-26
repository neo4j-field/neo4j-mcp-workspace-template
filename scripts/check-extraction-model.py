"""One bounded structured-output request using the extraction runtime parameters.

No graph access or user data. Run via setup.sh --check-model so dotenv is loaded.
Errors contain a category and recovery steps, never raw provider exception text.
"""
from __future__ import annotations

import asyncio
import os
import sys

import litellm
from pydantic import BaseModel, ConfigDict, ValidationError

from mcp_neo4j_entity_graph.base_extractor import build_llm_params, DEFAULT_EXTRACTION_MODEL


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    marker: str
    count: int


async def check_model(completion=None) -> None:
    params = build_llm_params(os.environ.get('EXTRACTION_MODEL', DEFAULT_EXTRACTION_MODEL), ProbeResult)
    params.update(messages=[{'role': 'user', 'content': 'Return JSON with marker="setup-ok" and count=2. No other fields.'}],
                  timeout=30, num_retries=0)
    response = await asyncio.wait_for((completion or litellm.acompletion)(**params), timeout=35)
    result = ProbeResult.model_validate_json(response.choices[0].message.content)
    if result.marker != 'setup-ok' or result.count != 2:
        raise ValueError('Unexpected structured result')


def main() -> int:
    try:
        asyncio.run(check_model())
    except (litellm.AuthenticationError, litellm.PermissionDeniedError):
        reason = 'Provider authentication or model access failed. Check the configured provider key and model permissions.'
    except (asyncio.TimeoutError, litellm.Timeout):
        reason = 'Provider timed out. Check connectivity and retry before importing data.'
    except litellm.RateLimitError:
        reason = 'Provider rate/quota limit reached. Check quota and retry.'
    except (ValidationError, ValueError, TypeError, IndexError, AttributeError):
        reason = 'The model did not return the required structured output. Choose a compatible extraction model/provider.'
    except Exception:
        reason = 'Model/provider request failed. Check EXTRACTION_MODEL, its provider prefix, credentials and structured-output support.'
    else:
        print('Extraction model preflight passed: structured output validated (no database writes).')
        return 0
    print(f'Extraction model preflight failed: {reason} Edit .env and rerun ./setup.sh --check-model. No ingestion or config generation was performed.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
