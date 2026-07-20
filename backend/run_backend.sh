#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

# LIA runtime defaults. Values from the repository .env are loaded
# afterwards and may override them.
: "${CORS_ALLOW_ORIGIN:=*}"
: "${ENABLE_BASE_MODELS_CACHE:=False}"
: "${OLLAMA_API_BASE_URL:=}"
: "${OPENAI_API_BASE_URL:=}"
: "${R2_ENABLED:=False}"
: "${REDIS_URL:=}"
: "${WEBUI_AUTH:=True}"
: "${COOKIES_SECURE:=False}"
: "${ENABLE_SIGNUP:=True}"
: "${FORCE_MIGRATION:=True}"
: "${FRONTEND_DEV:=true}"
: "${SKIP_TOOL_DEPS:=True}"
: "${HOST:=127.0.0.1}"
: "${PORT:=8080}"
: "${FORWARDED_ALLOW_IPS:=*}"
: "${UVICORN_WORKERS:=1}"
: "${BACKEND_RELOAD:=false}"
: "${OAUTH_SESSION_TOKEN_ENCRYPTION_KEY:=oauth-session-default-key}"

ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# External integrations. URLs intentionally have no hardcoded fallback:
# provide them in .env or in the process environment.
: "${RAGFLOW_URL:=}"
: "${RAGFLOW_API_KEY:=}"
: "${RAGFLOW_MINIO_URL:=}"
: "${LIA_ARIA_API_BASE_URL:=}"
: "${LIA_ARIA_API_KEY:=}"
: "${LIA_ARIA_MODEL:=/model}"
: "${LIA_OFFICE_ENABLED:=false}"
: "${LIA_OFFICECLI_BINARY:=$SCRIPT_DIR/bin/officecli}"
: "${LIA_OFFICECLI_WORK_DIR:=$SCRIPT_DIR/data/officecli}"
: "${LIA_OFFICECLI_TIMEOUT:=120}"
: "${LIA_LND_API_BASE_URL:=}"
: "${LIA_LND_API_KEY:=}"
: "${WEBUI_SECRET_KEY:=lia-0.2-local-development-secret-change-before-production}"

if [[ "$LIA_OFFICECLI_BINARY" != /* ]]; then
  LIA_OFFICECLI_BINARY="$REPO_ROOT/${LIA_OFFICECLI_BINARY#./}"
fi
if [[ "$LIA_OFFICECLI_WORK_DIR" != /* ]]; then
  LIA_OFFICECLI_WORK_DIR="$REPO_ROOT/${LIA_OFFICECLI_WORK_DIR#./}"
fi

if [[ -z "${LIA_LND_ENABLED+x}" ]]; then
  if [[ -n "$LIA_LND_API_BASE_URL" ]]; then
    LIA_LND_ENABLED=true
  else
    LIA_LND_ENABLED=false
  fi
fi

if [[ -z "${LIA_ARIA_ENABLED+x}" ]]; then
  if [[ -n "$LIA_ARIA_API_BASE_URL" ]]; then
    LIA_ARIA_ENABLED=true
  else
    LIA_ARIA_ENABLED=false
  fi
fi

validate_http_url() {
  local variable_name="$1"
  local value="$2"

  if [[ -n "$value" && ! "$value" =~ ^https?:// ]]; then
    echo "$variable_name must start with http:// or https://" >&2
    exit 1
  fi
}

is_true() {
  case "$1" in
    true | True | TRUE | 1 | yes | Yes | YES) return 0 ;;
    *) return 1 ;;
  esac
}

validate_http_url RAGFLOW_URL "$RAGFLOW_URL"
validate_http_url RAGFLOW_MINIO_URL "$RAGFLOW_MINIO_URL"
validate_http_url LIA_ARIA_API_BASE_URL "$LIA_ARIA_API_BASE_URL"
validate_http_url LIA_LND_API_BASE_URL "$LIA_LND_API_BASE_URL"

if [[ -n "$RAGFLOW_URL" && -z "$RAGFLOW_API_KEY" ]]; then
  echo "RAGFLOW_API_KEY is required when RAGFLOW_URL is set" >&2
  exit 1
fi

if [[ -z "$RAGFLOW_URL" && -n "$RAGFLOW_API_KEY" ]]; then
  echo "RAGFLOW_URL is required when RAGFLOW_API_KEY is set" >&2
  exit 1
fi

if is_true "$LIA_LND_ENABLED" && [[ -z "$LIA_LND_API_BASE_URL" ]]; then
  echo "LIA_LND_API_BASE_URL is required when LIA_LND_ENABLED=true" >&2
  exit 1
fi

if is_true "$LIA_ARIA_ENABLED" && [[ -z "$LIA_ARIA_API_BASE_URL" ]]; then
  echo "LIA_ARIA_API_BASE_URL is required when LIA_ARIA_ENABLED=true" >&2
  exit 1
fi

if is_true "$LIA_OFFICE_ENABLED"; then
  if ! is_true "$LIA_ARIA_ENABLED" || [[ -z "$LIA_ARIA_API_BASE_URL" ]]; then
    echo "LIA Office assistant requires the configured Aria OpenAI-compatible endpoint" >&2
    exit 1
  fi
  if [[ ! -x "$LIA_OFFICECLI_BINARY" ]]; then
    echo "OfficeCLI binary was not found at $LIA_OFFICECLI_BINARY" >&2
    echo "Run ./backend/install_officecli.sh or set LIA_OFFICECLI_BINARY" >&2
    exit 1
  fi
fi

export CORS_ALLOW_ORIGIN ENABLE_BASE_MODELS_CACHE OLLAMA_API_BASE_URL OPENAI_API_BASE_URL
export R2_ENABLED REDIS_URL WEBUI_AUTH COOKIES_SECURE ENABLE_SIGNUP FORCE_MIGRATION
export FRONTEND_DEV SKIP_TOOL_DEPS HOST PORT FORWARDED_ALLOW_IPS
export OAUTH_SESSION_TOKEN_ENCRYPTION_KEY WEBUI_SECRET_KEY
export RAGFLOW_URL RAGFLOW_API_KEY RAGFLOW_MINIO_URL
export LIA_ARIA_ENABLED LIA_ARIA_API_BASE_URL LIA_ARIA_API_KEY LIA_ARIA_MODEL
export LIA_OFFICE_ENABLED LIA_OFFICECLI_BINARY LIA_OFFICECLI_WORK_DIR LIA_OFFICECLI_TIMEOUT
export LIA_LND_ENABLED LIA_LND_API_BASE_URL LIA_LND_API_KEY

if [[ -n "${PYTHON_BIN:-}" ]]; then
  BACKEND_PYTHON="$PYTHON_BIN"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  BACKEND_PYTHON="$REPO_ROOT/.venv/bin/python"
elif [[ -x "$REPO_ROOT/../bin/python" ]]; then
  BACKEND_PYTHON="$REPO_ROOT/../bin/python"
elif command -v python3 >/dev/null 2>&1; then
  BACKEND_PYTHON="$(command -v python3)"
else
  echo "Python was not found. Set PYTHON_BIN or create $REPO_ROOT/.venv." >&2
  exit 1
fi

echo "Environment file: $ENV_FILE"
echo "RAGFlow URL: ${RAGFLOW_URL:-disabled}"
echo "RAGFlow MinIO URL: ${RAGFLOW_MINIO_URL:-disabled}"
echo "Aria URL: ${LIA_ARIA_API_BASE_URL:-disabled}"
echo "Aria model: ${LIA_ARIA_MODEL:-disabled}"
echo "Aria enabled: $LIA_ARIA_ENABLED"
echo "Office assistant enabled: $LIA_OFFICE_ENABLED"
echo "OfficeCLI binary: ${LIA_OFFICECLI_BINARY:-disabled}"
echo "SIP/LND URL: ${LIA_LND_API_BASE_URL:-disabled}"
echo "SIP/LND enabled: $LIA_LND_ENABLED"
echo "Starting LIA 0.2 backend at http://$HOST:$PORT"

UVICORN_ARGS=(
  -m uvicorn open_webui.main:app
  --host "$HOST"
  --port "$PORT"
  --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
)

if is_true "$BACKEND_RELOAD"; then
  UVICORN_ARGS+=(--reload)
else
  UVICORN_ARGS+=(--workers "$UVICORN_WORKERS")
fi

exec "$BACKEND_PYTHON" "${UVICORN_ARGS[@]}" "$@"
