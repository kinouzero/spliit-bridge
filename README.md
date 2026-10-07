# Spliit Bridge

A lightweight Python API bridge for Spliit. It exposes a small, API-key-protected interface for listing configured groups, retrieving group details and categories, previewing expense payloads, and optionally creating expenses.

The service uses Python's standard library only.

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

- `GET /api/groups/{group_id}`

Retrieves details for a configured group.

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
| `API_KEY` | Required | Shared API key; must be at least 32 characters |
| `ALLOW_CREATE` | `false` | Enables `POST /api/expenses` only when set to `true` |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per-process request limit per minute |
| `LOG_LEVEL` | `INFO` | Logging level |
