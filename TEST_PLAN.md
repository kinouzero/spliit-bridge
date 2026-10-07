# Spliit Bridge Test Plan

The test suite covers the current `app/server.py` implementation.

## Configuration

- Valid configuration loading.
- Missing configuration file.
- Invalid JSON.
- Invalid `groups` structure.
- Invalid group IDs.
- Empty or oversized group names.
- Duplicate group IDs.

## Authentication

- `X-API-Key`.
- `Authorization: Bearer`.
- Missing credentials.
- Invalid credentials.
- Conflicting credential sources.

## Health

- `/health`.
- `/healthz`.
- `/bridge/health`.
- No authentication required for health endpoints.

## Groups and categories

- List configured groups.
- Unknown routes.
- Unknown group details.
- Categories proxy.
- Group details proxy.

## Expense validation

- Amount parsing and EUR limits.
- Comma decimal separator.
- Maximum two decimal places.
- Split modes.
- Shares validation.
- Title validation.
- Date validation.
- Category validation.
- Participant validation.
- Duplicate participants.
- Notes validation.

## Expense endpoints

- Preview is dry-run.
- Preview never calls `groups.expenses.create`.
- Creation is disabled by default.
- Creation works when explicitly enabled.
- Invalid JSON.
- Request size limit.
- Content-Type validation.
- Unsupported methods.

## Upstream

- Procedure-name validation.
- tRPC response unwrapping.
- Unknown tRPC shapes.
- JSON serialization rejects NaN.

## Rate limiting

- Requests above the configured per-process limit return HTTP 429.

## CI

Every push and pull request runs:
- Python compilation.
- flake8.
- pytest.
- Docker image build without push.

Version tags (`v*`) additionally:
- create a GitHub Release;
- build and push the Docker image to Docker Hub.
