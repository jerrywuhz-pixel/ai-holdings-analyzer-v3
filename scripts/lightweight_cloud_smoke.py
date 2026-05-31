#!/usr/bin/env python3
"""
Lightweight server production smoke for AI Holdings 3.0.

The script is intentionally stdlib-only and Python 3.6 compatible so it can run
on the lightweight server host. It exercises the user-facing cloud path and
cleans up the temporary smoke account afterwards.
"""

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


class CloudSmokeConfig(object):
    def __init__(
        self,
        webapp_base_url,
        data_service_base_url,
        openclaw_base_url,
        connector_pairing_token,
        email,
        password,
        tenant_id,
        env_file=".env.server",
        deploy_dir="/opt/ai-holdings-analyzer-v3",
        compose_file="docker-compose.server.yml",
        cleanup=True,
        quote_symbol="AAPL",
    ):
        self.webapp_base_url = webapp_base_url.rstrip("/")
        self.data_service_base_url = data_service_base_url.rstrip("/")
        self.openclaw_base_url = openclaw_base_url.rstrip("/")
        self.connector_pairing_token = connector_pairing_token
        self.email = email
        self.password = password
        self.tenant_id = tenant_id
        self.env_file = env_file
        self.deploy_dir = deploy_dir
        self.compose_file = compose_file
        self.cleanup = cleanup
        self.quote_symbol = quote_symbol


class StepResult(object):
    def __init__(self, step, status, detail, payload=None):
        self.step = step
        self.status = status
        self.detail = detail
        self.payload = payload

    def to_dict(self):
        return {
            "step": self.step,
            "status": self.status,
            "detail": self.detail,
            "payload": self.payload,
        }


def load_env_file(path):
    if not path or not os.path.exists(path):
        return
    with open(path, "r") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _request_json(method, url, payload=None, headers=None, opener=None, timeout=20):
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    active_opener = opener or urllib.request.build_opener()
    try:
        with active_opener.open(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return exc.code, parsed, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def _shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _sourceable_env_file(path):
    if os.path.isabs(path) or "/" in path:
        return path
    return "./" + path


def _run_host_script(config, script):
    command = ["bash", "-lc", script]
    process = subprocess.Popen(
        command,
        cwd=config.deploy_dir if os.path.isdir(config.deploy_dir) else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))
    return stdout.decode("utf-8", errors="replace")


def _lookup_local_verification_code(config, email):
    escaped_email = email.replace("'", "''")
    script = r"""
set -e
cd {deploy_dir}
set -a
. {env_file}
set +a
HASH="$(docker compose --env-file {env_file} -f {compose_file} exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT code_hash FROM public.local_auth_email_verifications WHERE email = '{email}' LIMIT 1;")"
if [ -z "$HASH" ]; then
  echo "verification code hash not found for smoke user" >&2
  exit 2
fi
python3 - "$AUTH_SESSION_SECRET" {email_arg} "$HASH" <<'PY'
import hashlib
import hmac
import sys

secret, email, expected = sys.argv[1], sys.argv[2].strip().lower(), sys.argv[3].strip()
for value in range(100000, 1000000):
    code = str(value)
    digest = hmac.new(secret.encode(), ("%s:%s" % (email, code)).encode(), hashlib.sha256).hexdigest()
    if digest == expected:
        print(code)
        break
else:
    raise SystemExit(3)
PY
""".format(
        deploy_dir=_shell_quote(config.deploy_dir),
        env_file=_shell_quote(_sourceable_env_file(config.env_file)),
        compose_file=_shell_quote(config.compose_file),
        email=escaped_email,
        email_arg=_shell_quote(email),
    )
    return _run_host_script(config, script).strip().splitlines()[-1]


def _cleanup_smoke_user(config, email):
    escaped_email = email.replace("'", "''")
    script = r"""
set -e
cd {deploy_dir}
set -a
. {env_file}
set +a
docker compose --env-file {env_file} -f {compose_file} exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At <<'SQL'
WITH target_public AS (
  SELECT id FROM public.users WHERE email = '{email}'
), deleted_public AS (
  DELETE FROM public.users WHERE id IN (SELECT id FROM target_public) RETURNING id
), deleted_auth AS (
  DELETE FROM auth.users WHERE email = '{email}' RETURNING id
), deleted_local AS (
  DELETE FROM public.local_auth_users WHERE email = '{email}' RETURNING id
), deleted_pending AS (
  DELETE FROM public.local_auth_email_verifications WHERE email = '{email}' RETURNING email
)
SELECT 'deleted_public_users=' || (SELECT count(*) FROM deleted_public)
UNION ALL SELECT 'deleted_auth_users=' || (SELECT count(*) FROM deleted_auth)
UNION ALL SELECT 'deleted_local_auth_users=' || (SELECT count(*) FROM deleted_local)
UNION ALL SELECT 'deleted_pending_verifications=' || (SELECT count(*) FROM deleted_pending);
SQL
""".format(
        deploy_dir=_shell_quote(config.deploy_dir),
        env_file=_shell_quote(_sourceable_env_file(config.env_file)),
        compose_file=_shell_quote(config.compose_file),
        email=escaped_email,
    )
    return _run_host_script(config, script)


def _record_step(steps, step, status_code, response_json, raw, validator):
    if 200 <= status_code < 300 and validator(response_json):
        steps.append(StepResult(step, "passed", "HTTP %s" % status_code, _safe_payload(response_json)))
        return True
    detail = "HTTP %s: %s" % (status_code or "network", _compact(raw))
    steps.append(StepResult(step, "failed", detail, _safe_payload(response_json)))
    return False


def _safe_payload(payload):
    if not isinstance(payload, dict):
        return payload
    safe = dict(payload)
    if isinstance(safe.get("auth"), dict):
        auth = dict(safe["auth"])
        for key in ("bot_token", "bot_token_ciphertext", "context_token"):
            if key in auth:
                auth[key] = "SET"
        safe["auth"] = auth
    return safe


def _compact(raw, limit=500):
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return text[:limit]


def _sample_sell_put_payload(tenant_id, symbol):
    now = datetime.utcnow()
    as_of = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expiry = (now + timedelta(days=32)).strftime("%Y-%m-%d")
    return {
        "tenant_id": tenant_id,
        "underlying_symbol": symbol,
        "quote": {
            "symbol": symbol,
            "as_of": as_of,
            "price": 190.0,
            "currency": "USD",
            "source_key": "futu_openapi",
            "source_tier": "L1_trading",
            "fallback_used": False,
            "cross_check_status": "matched",
        },
        "option_candidates": [
            {
                "contract_symbol": "%s260702P180" % symbol,
                "option_type": "put",
                "strike": 180.0,
                "contracts": 1,
                "expiry": expiry,
                "days_to_expiry": 32,
                "bid": 2.1,
                "ask": 2.25,
                "delta": -0.22,
                "implied_volatility": 0.32,
                "open_interest": 1200,
                "volume": 240,
                "as_of": as_of,
                "source_key": "futu_openapi",
                "source_tier": "L1_trading",
            }
        ],
        "account_snapshot": {
            "tenant_id": tenant_id,
            "broker_connection_id": "codex-smoke-broker",
            "broker": "futu",
            "source_key": "futu_openapi",
            "source_tier": "L1_trading",
            "connector_mode": "local_connector",
            "permission_scope": "read_only",
            "as_of": as_of,
            "received_at": as_of,
            "positions": [],
            "cash_balances": [{"currency": "USD", "available_cash": 50000, "buying_power": 100000}],
            "missing_fields": [],
            "status": "complete",
            "lineage": {"smoke": True},
        },
        "max_market_staleness_seconds": 300,
        "max_broker_staleness_seconds": 300,
    }


def run_smoke(config):
    if not config.connector_pairing_token:
        raise ValueError("connector pairing token is required for Futu connector poll smoke")

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    steps = []

    try:
        _run_smoke_steps(config, opener, steps)
    except Exception as exc:
        steps.append(StepResult("smoke_runtime", "failed", str(exc), None))
    finally:
        if config.cleanup:
            try:
                _cleanup_smoke_user(config, config.email)
            except Exception as exc:
                steps.append(StepResult("cleanup", "failed", str(exc), None))
    return _summary(steps)


def _run_smoke_steps(config, opener, steps):
    register_payload = {
        "email": config.email,
        "password": config.password,
        "confirmPassword": config.password,
        "displayName": "Codex Smoke",
    }
    status, payload, raw = _request_json(
        "POST", config.webapp_base_url + "/api/auth/register", payload=register_payload, opener=opener
    )
    if not _record_step(
        steps,
        "register",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("status") == "verification_required"
        and data.get("delivery") in {"email_sent", "server_log"},
    ):
        return

    code = _lookup_local_verification_code(config, config.email)
    status, payload, raw = _request_json(
        "POST",
        config.webapp_base_url + "/api/auth/verify",
        payload={"email": config.email, "code": code},
        opener=opener,
    )
    if not _record_step(
        steps,
        "verify_email",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("status") == "signed_in"
        and isinstance(data.get("user"), dict),
    ):
        return

    status, payload, raw = _request_json(
        "POST",
        config.webapp_base_url + "/api/onboarding/wechat/binding",
        payload={"action": "start"},
        opener=opener,
    )
    if not _record_step(
        steps,
        "wechat_binding_start",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("status") == "qr_pending"
        and isinstance(data.get("auth"), dict)
        and bool(data["auth"].get("qrcode") or data["auth"].get("qrcode_url")),
    ):
        return

    connector_payload = {
        "tenant_id": config.tenant_id,
        "connector_instance_id": "codex-smoke-connector",
        "capabilities": {"positions": True, "cash_balances": True},
    }
    status, payload, raw = _request_json(
        "POST",
        config.data_service_base_url + "/api/v3/connectors/poll",
        payload=connector_payload,
        headers={"X-Connector-Pairing-Token": config.connector_pairing_token},
    )
    if not _record_step(
        steps,
        "futu_connector_poll",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("ok") is True
        and isinstance(data.get("data"), dict)
        and bool(data["data"].get("tasks")),
    ):
        return

    portfolio_url = "%s/api/v3/portfolio/overview?%s" % (
        config.data_service_base_url,
        urllib.parse.urlencode({"tenant_id": config.tenant_id}),
    )
    status, payload, raw = _request_json("GET", portfolio_url)
    if not _record_step(
        steps,
        "portfolio_overview",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("ok") is True
        and isinstance(data.get("data"), dict)
        and data["data"].get("freshness"),
    ):
        return

    status, payload, raw = _request_json(
        "GET", config.data_service_base_url + "/api/quote/" + urllib.parse.quote(config.quote_symbol)
    )
    if not _record_step(
        steps,
        "quote",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict) and data.get("ok") is True and isinstance(data.get("data"), dict),
    ):
        return

    status, payload, raw = _request_json(
        "POST",
        config.data_service_base_url + "/api/v3/options/sell-put/analyze",
        payload=_sample_sell_put_payload(config.tenant_id, config.quote_symbol),
    )
    if not _record_step(
        steps,
        "sell_put",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict)
        and data.get("ok") is True
        and isinstance(data.get("data"), dict)
        and data["data"].get("overall_actionability") in {"trade_draft", "analysis_only", "blocked"},
    ):
        return

    ingress_payload = {
        "routing": {
            "tenant_id": config.tenant_id,
            "channel": "openclaw_wechat",
            "openclaw_account_id": "codex-smoke",
            "context_token": "codex-smoke",
        },
        "message": {
            "id": "codex-smoke-%s" % int(time.time()),
            "type": "event",
            "metadata": {"kind": "smoke"},
        },
    }
    status, payload, raw = _request_json(
        "POST", config.openclaw_base_url + "/api/openclaw/wechat/messages", payload=ingress_payload
    )
    _record_step(
        steps,
        "openclaw_ingress",
        status,
        payload,
        raw,
        lambda data: isinstance(data, dict) and data.get("result_type") in {"ignored", "model_reply"},
    )


def _summary(steps):
    counts = {"passed": 0, "failed": 0}
    for step in steps:
        counts[step.status] = counts.get(step.status, 0) + 1
    return {
        "status": "fail" if counts.get("failed") else "pass",
        "counts": counts,
        "steps": [step.to_dict() for step in steps],
    }


def _default_email(webapp_base_url):
    host = urllib.parse.urlparse(webapp_base_url).hostname or "11office.top"
    return "codex-smoke-%s@%s" % (datetime.utcnow().strftime("%Y%m%d%H%M%S"), host)


def parse_args():
    parser = argparse.ArgumentParser(description="Run lightweight cloud production smoke.")
    parser.add_argument("--env-file", default=os.getenv("SMOKE_ENV_FILE", ".env.server"))
    parser.add_argument("--deploy-dir", default=os.getenv("REMOTE_DEPLOY_DIR", "/opt/ai-holdings-analyzer-v3"))
    parser.add_argument("--compose-file", default=os.getenv("SMOKE_COMPOSE_FILE", "docker-compose.server.yml"))
    parser.add_argument("--webapp-base-url", default=os.getenv("WEBAPP_BASE_URL", "https://www.11office.top"))
    parser.add_argument("--data-service-base-url", default=os.getenv("SMOKE_DATA_SERVICE_BASE_URL", "http://172.17.0.1:8000"))
    parser.add_argument("--openclaw-base-url", default=os.getenv("SMOKE_OPENCLAW_BASE_URL", "http://172.17.0.1:8080"))
    parser.add_argument("--connector-pairing-token", default=os.getenv("FUTU_CONNECTOR_PAIRING_TOKEN", ""))
    parser.add_argument("--tenant-id", default=os.getenv("SMOKE_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default=os.getenv("SMOKE_PASSWORD", "CodexSmoke123!"))
    parser.add_argument("--quote-symbol", default=os.getenv("SMOKE_QUOTE_SYMBOL", "AAPL"))
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main():
    args = parse_args()
    load_env_file(args.env_file)
    webapp_base_url = args.webapp_base_url.rstrip("/")
    config = CloudSmokeConfig(
        webapp_base_url=webapp_base_url,
        data_service_base_url=args.data_service_base_url,
        openclaw_base_url=args.openclaw_base_url,
        connector_pairing_token=args.connector_pairing_token or os.getenv("FUTU_CONNECTOR_PAIRING_TOKEN", ""),
        email=args.email or _default_email(webapp_base_url),
        password=args.password,
        tenant_id=args.tenant_id,
        env_file=args.env_file,
        deploy_dir=args.deploy_dir,
        compose_file=args.compose_file,
        cleanup=not args.no_cleanup,
        quote_symbol=args.quote_symbol,
    )
    summary = run_smoke(config)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as handle:
            handle.write(rendered)
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
