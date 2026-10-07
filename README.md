# Spliit Bridge

A lightweight Python API bridge for [Spliit](https://github.com/spliit-app/spliit). It exposes a small, API-key-protected interface for listing configured groups, retrieving group details and categories, previewing expense payloads, and optionally creating expenses.

The service uses Python's standard library only.

## Disclaimer

This is an independent, unofficial project. It is not affiliated with, endorsed by, or maintained by the Spliit project or its contributors. The Spliit name is used solely to identify the application this bridge integrates with.

## Features

- API key authentication through `X-API-Key` or `Authorization: Bearer <key>`.
- Health endpoints at `/health` and `/healthz`.
- Configurable group allowlist in `config.json`.
- Expense preview endpoint that does not create an expense.
- Expense creation disabled by default; enable it explicitly with `ALLOW_CREATE=true`.
- Request body size limit and basic per-process rate limiting.
- Docker image runs as a non-root user, with a read-only root filesystem and dropped Linux capabilities in Compose.

## Requirements

- Docker Engine and Docker Compose.
- Spliit reachable from the bridge container.
- An existing Docker network shared with Spliit (default: `spliit-net`).

## Quick start

### 1. Get the project files

Clone your repository or extract the project archive.

### 2. Configure environment variables

Copy the example environment file:

```sh
cp .env.example .env
```

Generate a strong API key (at least 32 characters; 64 random hexadecimal characters are a good option):

```sh
openssl rand -hex 32
```

Put the generated value in `.env`:

```dotenv
API_KEY=YOUR_GENERATED_SECRET
SPLIIT_BASE_URL=http://spliit:3000
ALLOW_CREATE=false
SPLIIT_DOCKER_NETWORK=spliit-net
RATE_LIMIT_PER_MINUTE=120
LOG_LEVEL=INFO
```

### 3. Configure allowed groups

Edit `config.json` and replace the example IDs and names with your actual Spliit group IDs and readable names:

```json
{
  "groups": [
    {
      "id": "YOUR_GROUP_ID",
      "name": "Shared expenses"
    },
    {
      "id": "YOUR_SECOND_GROUP_ID",
      "name": "Household bills"
    }
  ]
}
```

Only configure groups that this bridge should expose.

### 4. Check the Docker network

By default, Compose expects an existing Docker network named `spliit-net`. If your Spliit container uses a different network, set `SPLIIT_DOCKER_NETWORK` in `.env` to that network's name.

The value of `SPLIIT_BASE_URL` must resolve from inside the bridge container. For example, `http://spliit:3000` works only if the Spliit service/container is reachable under the hostname `spliit` on the shared network.

### 5. Start the bridge

```sh
docker compose up -d --build
```

View logs:

```sh
docker compose logs -f spliit-bridge
```

Check health locally:

```sh
curl http://127.0.0.1:8787/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "spliit-bridge"
}
```

The Compose file binds the port to `127.0.0.1` by default, so it is not directly exposed on all host interfaces.

## API

All endpoints except `/health` and `/healthz` require an API key. Send it using either:

```http
X-API-Key: YOUR_API_KEY
```

or:

```http
Authorization: Bearer YOUR_API_KEY
```

The bridge accepts requests with or without the optional `/bridge` prefix.

### Health

- `GET /health`
- `GET /healthz`

No authentication required.

### List configured groups

- `GET /api/groups`

Returns the groups allowed by `config.json`.

### Get group details

- `GET /api/groups/{group_id}/details`

Retrieves details for a configured group. The group and its participants are returned under `data.group`.

### List categories

- `GET /api/categories`

Retrieves categories from Spliit.

### Preview an expense

- `POST /api/expenses/preview`

Validates the submitted expense payload and returns a preview. It does **not** create an expense.

### Create an expense

- `POST /api/expenses`

Expense creation is disabled by default. To enable it, set:

```dotenv
ALLOW_CREATE=true
```

Restart/recreate the container after changing the environment:

```sh
docker compose up -d
```

Only enable creation once you have tested the preview endpoint and verified the payloads.

### Expense payload and validation

Both expense endpoints accept the same JSON object:

```json
{
  "groupId": "YOUR_GROUP_ID",
  "title": "Lunch",
  "amount": "12.50",
  "expenseDate": "2026-10-07T12:00:00Z",
  "paidBy": "PARTICIPANT_1",
  "paidFor": [
    {"participant": "PARTICIPANT_1", "shares": 1},
    {"participant": "PARTICIPANT_2", "shares": 1}
  ],
  "category": 1,
  "splitMode": "EVENLY",
  "notes": "Optional notes"
}
```

- `amount` is in euros, strictly positive, at most 100000, with at most two decimal places. Comma decimals are accepted. The upstream payload and preview use integer cents.
- `expenseDate` accepts an ISO date or datetime, from year 2000 through the current year plus two. Offsets are converted to UTC; dates without a timezone are interpreted as UTC. The preview and upstream request use an explicit `Z` suffix.
- `title` must contain 2–200 characters after trimming; control characters are rejected. Optional `notes` allow 2000 characters, including newlines and tabs.
- `paidBy` and all `paidFor` participants must belong to the configured group. `paidFor` accepts 1–100 distinct participants. Shares default to 1 and must be positive and at most 1000000.
- `category` must be an integer from 0 to 10000.

| `splitMode` | Meaning of `paidFor[].shares` |
|---|---|
| `EVENLY` | Equal split; use the default share of 1 |
| `BY_SHARES` | Relative weights, with at most two decimal places |
| `BY_PERCENTAGE` | Percentages with at most two decimal places, totaling exactly 100 |
| `BY_AMOUNT` | Integer cents totaling exactly the expense amount in cents; for €12.50, use e.g. 625 + 625 |

The bridge checks split totals and precision before previewing or creating an expense. Participant extraction follows the explicit list in [Spliit's group details response](https://github.com/spliit-app/spliit/blob/main/src/trpc/routers/groups/getDetails.procedure.ts); share units follow its [expense schema](https://github.com/spliit-app/spliit/blob/main/src/lib/schemas.ts). Direct group objects with `participants` or `members` are also accepted for compatibility.

Requests require `Content-Type: application/json` and a single valid `Content-Length`, with a maximum body size of 16 KiB. Transfer encoding is unsupported. Socket inactivity is limited to 10 seconds; a timeout while reading the body returns HTTP 408. Invalid expenses return 400, invalid credentials 401, excessive request rates 429, and configuration/upstream failures 502.

`config.json` must contain a `groups` array; an empty array allows no groups. Changes are reloaded on each request. Invalid or unreadable configuration fails closed.

## Security notes

- Use a strong, unique API key of at least 32 characters.
- The service is bound to `127.0.0.1:8787` by default. If you change the binding, protect it with your firewall and/or a reverse proxy.
- Keep `ALLOW_CREATE=false` until you explicitly need expense creation.
- The rate limiter is in-process; it is not shared across multiple replicas.
- The bridge does not provide an idempotency guarantee. Retrying an expense-creation request may create a duplicate expense.
- Use HTTPS when requests cross an untrusted network.

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Address listened to inside the container |
| `PORT` | `8787` | HTTP port |
| `CONFIG_PATH` | `/app/config.json` | Path to the JSON group configuration |
| `SPLIIT_BASE_URL` | `http://spliit:3000` | Base URL of the Spliit service, reachable from the bridge container |
| `API_KEY` | Required | Shared API key; must be at least 32 ASCII characters |
| `ALLOW_CREATE` | `false` | Enables `POST /api/expenses` only when set to `true` |
| `RATE_LIMIT_PER_MINUTE` | `120` | Positive per-process, per-client-IP request limit per minute |
| `LOG_LEVEL` | `INFO` | Logging level |

## Development and tests

Python 3.12 or newer is required for development. Runtime dependencies remain limited to the standard library.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m compileall -q app tests
flake8 app tests
pytest -q
```

`pytest.ini` measures all of `app`, including branches, and requires **100% coverage**. Every run generates `htmlcov/index.html` and `coverage.xml`; these generated files are ignored by Git. To run a focused test without the full-suite coverage gate, use e.g. `pytest --no-cov tests/test_auth.py`.

Tests use local HTTP servers and controlled network failures; they need no running Spliit instance, Docker daemon, or external network.

CI runs compilation, lint, and tests on Python 3.12 and 3.13, uploads coverage reports for each version, then builds the Docker image. Release publishing remains restricted to version tags.
