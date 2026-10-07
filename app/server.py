#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import string
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8787"))
CONFIG_FILE = os.getenv("CONFIG_PATH", "/app/config.json")
SPLIIT_BASE_URL = os.getenv("SPLIIT_BASE_URL", "http://spliit:3000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
ALLOW_CREATE = os.getenv("ALLOW_CREATE", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_BODY = 16 * 1024
MAX_AMOUNT_EUR = Decimal("100000")
MAX_SHARES = Decimal("1000000")
ALLOWED_SPLIT_MODES = {"EVENLY", "BY_SHARES", "BY_AMOUNT", "BY_PERCENTAGE"}
ALLOWED_ID_CHARS = string.ascii_letters + string.digits + "_-"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
LOG = logging.getLogger("spliit_bridge")

# Lightweight per-process throttling. Also configure rate limits at the reverse proxy.
RATE_WINDOW = 60.0
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
_rate_lock = threading.Lock()
_requests: dict[str, deque[float]] = defaultdict(deque)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict) or not isinstance(config.get("groups", []), list):
        raise ValueError("Invalid config structure")
    groups, seen = config.get("groups", []), set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Invalid group configuration")
        gid, name = group.get("id"), group.get("name")
        if not isinstance(gid, str) or not ID_RE.fullmatch(gid):
            raise ValueError("Invalid group id in config")
        if gid in seen:
            raise ValueError("Duplicate group id in config")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Invalid group name in config")
        seen.add(gid)
    return config


CONFIG = None
CONFIG_LOCK = threading.Lock()


def get_config():
    # Read the small config on demand so config changes apply without restart.
    # Fail closed if it becomes unreadable or invalid.
    with CONFIG_LOCK:
        return load_config()


def unwrap_trpc(payload):
    try:
        return payload["result"]["data"]["json"]
    except (KeyError, TypeError):
        return payload


def upstream_call(procedure, input_value=None, *, mutation=False, date_paths=None):
    if not re.fullmatch(r"[A-Za-z0-9_.]+", procedure):
        raise ValueError("Invalid upstream procedure")
    url = f"{SPLIIT_BASE_URL}/api/trpc/{quote(procedure, safe='.')}"
    if mutation:
        payload = {"json": input_value}
        if date_paths:
            payload["meta"] = {"values": {p: ["Date"] for p in date_paths}}
        data = json_bytes(payload)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        req = Request(url, data=data, headers=headers, method="POST")
    else:
        if input_value is not None:
            encoded = json.dumps({"json": input_value}, separators=(",", ":"), ensure_ascii=False)
            url += "?" + urlencode({"input": encoded})
        req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=10 if not mutation else 15) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise RuntimeError("upstream_response_too_large")
            result = json.loads(raw.decode("utf-8"))
            if isinstance(result, dict) and result.get("error"):
                # Do not propagate upstream error bodies to public clients/logs.
                raise RuntimeError("upstream_rejected_request")
            return unwrap_trpc(result)
    except HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        raise RuntimeError(f"upstream_http_{exc.code}") from None
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("upstream_unavailable") from None


def spliit_query(procedure, input_value=None):
    return upstream_call(procedure, input_value)


def spliit_mutation(procedure, input_value, date_paths=None):
    return upstream_call(procedure, input_value, mutation=True, date_paths=date_paths)


def allowed_group(group_id):
    if not isinstance(group_id, str):
        return None
    for group in get_config()["groups"]:
        if group["id"] == group_id:
            return group
    return None


def participant_ids_from_details(value):
    """Extract candidate participant IDs from known participant-like objects."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            oid = obj.get("id")
            if isinstance(oid, str) and ID_RE.fullmatch(oid) and any(
                key in obj for key in ("name", "user", "isUser", "email", "color")
            ):
                found.add(oid)
            for child in obj.values():
                walk(child)
        elif isinstance(obj, list):
            for child in obj:
                walk(child)
    walk(value)
    return found


def parse_amount(value):
    if isinstance(value, bool) or isinstance(value, (dict, list)) or value is None:
        raise ValueError("Invalid amount")
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid amount") from None
    if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT_EUR:
        raise ValueError("Amount must be positive and within the configured limit")
    cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if cents <= 0:
        raise ValueError("Amount is below the minimum supported value")
    # Reject precision beyond cents rather than silently altering an expense.
    if amount != (cents / Decimal(100)):
        raise ValueError("Amount may contain at most two decimal places")
    return amount, int(cents)


def parse_expense(body):
    required = ("groupId", "title", "amount", "expenseDate", "paidBy", "paidFor", "category", "splitMode")
    missing = [key for key in required if key not in body]
    if missing:
        raise ValueError("Missing required fields")
    group_id = body["groupId"]
    if not isinstance(group_id, str) or not allowed_group(group_id):
        raise ValueError("Group not allowed")
    title = body["title"]
    if not isinstance(title, str):
        raise ValueError("Invalid title")
    title = title.strip()
    if not 2 <= len(title) <= 200 or any(ord(c) < 32 for c in title):
        raise ValueError("Title must contain 2-200 printable characters")
    amount, amount_cents = parse_amount(body["amount"])
    split_mode = body["splitMode"]
    if not isinstance(split_mode, str) or split_mode not in ALLOWED_SPLIT_MODES:
        raise ValueError("Invalid splitMode")
    date_value = body["expenseDate"]
    if not isinstance(date_value, str) or len(date_value) > 64:
        raise ValueError("Invalid expenseDate")
    try:
        parsed_date = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("expenseDate must be a valid ISO date") from None
    if parsed_date.tzinfo is not None:
        parsed_date = parsed_date.astimezone(timezone.utc).replace(tzinfo=None)
    # Reject obviously unreasonable dates.
    if parsed_date.year < 2000 or parsed_date.year > datetime.now(timezone.utc).year + 2:
        raise ValueError("expenseDate is outside the accepted range")
    category = body["category"]
    if not isinstance(category, int) or isinstance(category, bool) or not 0 <= category <= 10000:
        raise ValueError("Invalid category")
    paid_by = body["paidBy"]
    if not isinstance(paid_by, str) or not ID_RE.fullmatch(paid_by):
        raise ValueError("Invalid paidBy")
    paid_for = body["paidFor"]
    if not isinstance(paid_for, list) or not 1 <= len(paid_for) <= 100:
        raise ValueError("paidFor must contain between 1 and 100 entries")
    normalized, seen = [], set()
    for item in paid_for:
        if not isinstance(item, dict):
            raise ValueError("Invalid paidFor entry")
        participant = item.get("participant")
        if not isinstance(participant, str) or not ID_RE.fullmatch(participant):
            raise ValueError("Invalid participant ID")
        if participant in seen:
            raise ValueError("Duplicate participant in paidFor")
        seen.add(participant)
        raw_shares = item.get("shares", 1)
        if isinstance(raw_shares, bool) or isinstance(raw_shares, (dict, list)):
            raise ValueError("Invalid shares value")
        try:
            shares = Decimal(str(raw_shares).strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValueError("Invalid shares value") from None
        if not shares.is_finite() or shares <= 0 or shares > MAX_SHARES:
            raise ValueError("Shares must be positive and within the configured limit")
        normalized.append({"participant": participant, "shares": str(shares.normalize())})
    notes = body.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 2000 or any(ord(c) < 32 and c not in "\n\r\t" for c in notes):
        raise ValueError("Notes must be text up to 2000 characters")
    return {"groupId": group_id, "title": title, "amount": amount, "amountCents": amount_cents,
            "expenseDate": parsed_date, "paidBy": paid_by, "paidFor": normalized,
            "category": category, "splitMode": split_mode, "notes": notes}


def rate_limited(ip):
    now = time.monotonic()
    with _rate_lock:
        q = _requests[ip]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
        return False


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32


class BridgeHandler(BaseHTTPRequestHandler):
    # Suppress Python/version banner; don't echo user-controlled paths in logs.
    server_version = "SpliitBridge"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        LOG.info("client=%s request", self.client_address[0])

    def send_json(self, status, value):
        try:
            body = json_bytes(value)
        except (TypeError, ValueError):
            status, body = 500, b'{"error":"internal_error"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def route_path(self):
        # Do not percent-decode route paths: IDs are restricted to safe characters.
        path = urlsplit(self.path).path
        if path == "/bridge":
            return "/"
        if path.startswith("/bridge/"):
            return path[len("/bridge"):]
        return path

    def authorized(self):
        if not API_KEY:
            return False
        x_key = self.headers.get("X-API-Key", "")
        auth = self.headers.get("Authorization", "")
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        # Reject conflicting credential sources instead of silently choosing one.
        if x_key and bearer and not hmac.compare_digest(x_key, bearer):
            return False
        supplied = x_key or bearer
        return bool(supplied) and hmac.compare_digest(supplied, API_KEY)

    def _preflight(self):
        if rate_limited(self.client_address[0]):
            self.send_json(429, {"error": "rate_limited"})
            return False
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        path = self.route_path()
        # Health is intentionally minimal; restrict it at proxy/firewall if desired.
        if path in ("/health", "/healthz"):
            return self.send_json(200, {"status": "ok", "service": "spliit-bridge"})
        if not self._preflight():
            return
        try:
            if path == "/api/groups":
                groups = [{"id": g["id"], "name": g["name"]} for g in get_config()["groups"]]
                return self.send_json(200, {"data": {"groups": groups}})
            if path == "/api/categories":
                return self.send_json(200, {"data": spliit_query("categories.list")})
            match = re.fullmatch(r"/api/groups/([A-Za-z0-9_-]{1,128})/details", path)
            if match:
                gid = match.group(1)
                if not allowed_group(gid):
                    return self.send_json(404, {"error": "not_found"})
                data = spliit_query("groups.getDetails", {"groupId": gid})
                return self.send_json(200, {"data": data})
            return self.send_json(404, {"error": "not_found"})
        except Exception:
            LOG.exception("GET request failed")
            return self.send_json(502, {"error": "upstream_or_config_error"})

    def do_POST(self):
        if not self._preflight():
            return
        path = self.route_path()
        if path not in ("/api/expenses/preview", "/api/expenses"):
            return self.send_json(404, {"error": "not_found"})
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            return self.send_json(415, {"error": "application_json_required"})
        length_header = self.headers.get("Content-Length")
        if length_header is None or not length_header.isascii() or not length_header.isdigit():
            return self.send_json(411, {"error": "content_length_required"})
        length = int(length_header)
        if length <= 0:
            return self.send_json(400, {"error": "empty_body"})
        if length > MAX_BODY:
            return self.send_json(413, {"error": "request_too_large"})
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.send_json(400, {"error": "incomplete_body"})
            body = json.loads(
                raw.decode("utf-8"),
                parse_constant=lambda _x: (_ for _ in ()).throw(
                    ValueError("invalid_number")
                ),
            )
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "json_object_required"})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self.send_json(400, {"error": "invalid_json"})
        try:
            expense = parse_expense(body)
            details = spliit_query("groups.getDetails", {"groupId": expense["groupId"]})
            participant_ids = participant_ids_from_details(details)
            if not participant_ids:
                LOG.error("Could not validate participant list from Spliit details")
                return self.send_json(502, {"error": "participant_validation_unavailable"})
            if expense["paidBy"] not in participant_ids:
                return self.send_json(400, {"error": "invalid_paidBy"})
            if any(item["participant"] not in participant_ids for item in expense["paidFor"]):
                return self.send_json(400, {"error": "invalid_paidFor_participant"})
            preview = {"groupId": expense["groupId"], "title": expense["title"],
                       "amount": expense["amountCents"], "expenseDate": expense["expenseDate"].isoformat(),
                       "paidBy": expense["paidBy"], "paidFor": expense["paidFor"],
                       "category": expense["category"], "splitMode": expense["splitMode"]}
            if path == "/api/expenses/preview":
                return self.send_json(200, {"mode": "dry-run", "creation_enabled": ALLOW_CREATE,
                                            "would_create": preview,
                                            "message": "Preview only; no expense was created."})
            if not ALLOW_CREATE:
                return self.send_json(403, {"error": "creation_disabled"})
            expense_form = {"title": expense["title"], "amount": expense["amountCents"],
                            "expenseDate": expense["expenseDate"].isoformat(),
                            "category": expense["category"], "paidBy": expense["paidBy"],
                            "paidFor": expense["paidFor"], "splitMode": expense["splitMode"],
                            "saveDefaultSplittingOptions": False, "isReimbursement": False,
                            "documents": [], "notes": expense["notes"], "recurrenceRule": "NONE"}
            expense_id = "".join(secrets.choice(ALLOWED_ID_CHARS) for _ in range(21))
            result = spliit_mutation("groups.expenses.create",
                                     {"groupId": expense["groupId"], "expenseFormValues": expense_form,
                                      "participantId": expense["paidBy"], "expenseId": expense_id},
                                     date_paths=["expenseFormValues.expenseDate"])
            return self.send_json(201, {"created": True, "result": result})
        except ValueError as exc:
            # Validation messages are intentionally generic to avoid leaking config internals.
            return self.send_json(400, {"error": "invalid_expense", "message": str(exc)[:160]})
        except Exception:
            LOG.exception("POST request failed")
            return self.send_json(502, {"error": "upstream_or_config_error"})

    def do_PUT(self):
        return self.send_json(405, {"error": "method_not_allowed"})
    do_PATCH = do_PUT
    do_DELETE = do_PUT
    do_OPTIONS = do_PUT


def main():
    global CONFIG
    if len(API_KEY) < 32:
        raise SystemExit("API_KEY must be at least 32 characters; use a random secret")
    parsed = urlsplit(SPLIIT_BASE_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise SystemExit("SPLIIT_BASE_URL must be a valid http(s) URL without embedded credentials")
    if not 1 <= PORT <= 65535:
        raise SystemExit("PORT is invalid")
    CONFIG = load_config()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = BridgeHTTPServer((HOST, PORT), BridgeHandler)
    LOG.info("Spliit bridge listening on %s:%s (creation_enabled=%s)", HOST, PORT, ALLOW_CREATE)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
