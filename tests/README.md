# Polygraph Tests Directory

This directory contains unit and integration tests for the Polygraph verification battery.

## Test Organization

- `test_*.py` — Unit tests for specific components (CLI, fixtures, artifacts, etc.)
- `integration/test_verify.py` — Integration tests that exercise the full polygraph CLI flow via subprocess

## Running Tests

### Basic pytest run (unit tests)
```bash
cd /home/stefan/Projects/Polygraph
pytest tests/ -v
```

### Run integration tests separately (requires model + network access, or use CI skip marker)
```bash
pytest tests/integration/test_verify.py -m integration -v --timeout=300
```

Integration tests:
- Use `subprocess.run()` to invoke the real polygraph CLI (`scripts/run_polygraph_clean.py`)
- Test exit codes (0=PASS, 1=FAIL with --force-fail)
- Validate output structure (test_id, name, status, description fields)
- Check manifest fields from Stage 3

### Skip integration tests in CI (when no model available)
```bash
pytest tests/integration/test_verify.py -m "not integration" -v
pytest tests/ -v --ignore=tests/integration
```

## Adding New Integration Tests

1. Create a new test file in `tests/integration/`
2. Mark with `@pytest.mark.integration` decorator
3. Use subprocess to invoke CLI commands
4. Validate output against expected schema
5. Add documentation to this README.md if needed

## Notes on Test Markers

- Integration tests use `--output json` by default for easier parsing
- Tests may require an active model (ollama or openai) available at runtime
- If no network/model is available, integration tests will skip with clear message
- CI pipelines should gate integration tests separately from unit tests
