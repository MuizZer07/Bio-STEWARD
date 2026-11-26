---
name: no-paid-tests
description: Keep tests free of live paid calls to LLM APIs or cloud services; use recorded fixtures. Use when writing or running tests or verification scripts for code calling paid services.
---

# No live paid calls in tests

Start by saying in one line that you are using this skill and why.

A test suite runs often: locally, in CI, by agents in a loop. If it makes live paid calls, every run spends money,
results drift with the remote model, and failures become flaky. Tests must be free and repeatable; live calls are
runs, and runs need an estimate and a human's go-ahead.

## Rules
1. **Default test runs make no live paid call.** That includes LLM APIs, embedding APIs, cloud compute, paid
   databases and anything that bills per request.
2. **"Verification" and "smoke" scripts count as tests** if they are run routinely. The same rule applies.
3. **Use recorded fixtures:** stored request/response pairs, a fake client, or dependency injection of a stub. Keep
   fixtures small and synthetic; never store secrets or private data in them.
4. **Live integration tests are opt-in only:** a separate marker (for example `@pytest.mark.live`), excluded by
   default, and guarded by an explicit environment variable. Running them is a paid run: state an estimate (see
   `run-estimate`) and get the human's go-ahead.
5. **A confirmatory evaluation that needs paid calls is a run, not a test.** It follows the benchmark contract and
   the run rules, not the test suite.

## The spend guard
Paid calls in project code go through the guard; tests set `STEWARD_NO_PAID_CALLS=1`, which refuses every guarded call:
```python
from steward import spend
call = spend.guard(root, cfg, "model-name", est_in, est_out, authorization="steward/auth/<nonce>")
# ... make the call ...
spend.record(root, cfg, call, usage.input_tokens, usage.output_tokens, request_id=resp_id)
```
The guard refuses past the cap in `[spend]`, beyond the human-signed budget (`steward authorize prepare spend --budget
"USD 20 calls=200" ...`), after the authorization expires, and at unknown prices. It records estimates and actual
usage separately; the provider's bill is authoritative. Calls that bypass the guard are not seen. The authorization's
`--object` (e.g. a budget request file) is recorded for the human to read; what is enforced is the budget, the call
ceiling and the expiry.

## How to check a repository
- Search tests for client construction and network use (for example `grep -rnE "OpenAI\(|Anthropic\(|boto3|requests\.(get|post)" tests/`).
- Run the suite with the network blocked to find hidden calls: a socket-blocking plugin (for example
  `pytest-socket`), or patch `socket.socket` in a fixture, as this toolkit's own tests do.
- Check that CI does not expose provider API keys to the default test job.
- Check that a missing API key makes tests skip or use fakes, never fall back to a live call.

## When you find a live call in a test
Do not delete the test. Replace the live call with a fixture or stub that checks the same behaviour, move the live
version behind the opt-in marker, and tell the human what changed.

## Do not
- Add a live call to make a flaky test pass.
- Put a real API key in a fixture, a test file or a CI log.
- Treat "it only costs a little per run" as an exception; costs multiply with every run.
