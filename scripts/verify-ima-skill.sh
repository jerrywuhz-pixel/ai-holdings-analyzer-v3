#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

load_env_defaults() {
  local file="$1"
  local raw_line line key value
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%$'\r'}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'* && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    if [[ -n "$key" && -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}

if [[ -f "$ENV_FILE" ]]; then
  load_env_defaults "$ENV_FILE"
fi

SKILL_DIR="${IMA_SKILL_DIR:-$PROJECT_ROOT/openclaw/skills/ima-skill}"
if [[ "$SKILL_DIR" != /* ]]; then
  SKILL_DIR="$PROJECT_ROOT/$SKILL_DIR"
fi

echo "[ima] skill dir: $SKILL_DIR"
test -f "$SKILL_DIR/SKILL.md"
test -f "$SKILL_DIR/meta.json"
test -f "$SKILL_DIR/ima_api.cjs"
test -f "$SKILL_DIR/knowledge-base/SKILL.md"
test -f "$SKILL_DIR/notes/SKILL.md"

node -e "const meta=require(process.argv[1]); if (meta.version !== '1.1.7') { throw new Error('unexpected IMA skill version '+meta.version); } console.log('[ima] version='+meta.version)" "$SKILL_DIR/meta.json"
node -e "const v=process.versions.node.split('.').map(Number); if (v[0] < 18) throw new Error('Node >=18 required'); console.log('[ima] node='+process.version)"

tmp_dir="$(mktemp -d -t ima-preflight-XXXXXX)"
tmp_file="$tmp_dir/ima-preflight.md"
tmp_json="$tmp_dir/preflight.json"
trap 'rm -rf "$tmp_dir"' EXIT
printf '# IMA preflight\n\nThis is a local verification file.\n' > "$tmp_file"
node "$SKILL_DIR/knowledge-base/scripts/preflight-check.cjs" --file "$tmp_file" >"$tmp_json"
node -e "const d=require('fs').readFileSync(process.argv[1],'utf8'); const j=JSON.parse(d); if (!j.pass || j.media_type !== 7) throw new Error('preflight failed: '+d); console.log('[ima] preflight=pass media_type='+j.media_type)" "$tmp_json"

if [[ -n "${IMA_OPENAPI_CLIENTID:-}" && -n "${IMA_OPENAPI_APIKEY:-}" ]]; then
  echo "[ima] credentials detected; checking official API auth/update endpoint"
  response="$(node "$SKILL_DIR/ima_api.cjs" "openapi/check_skill_update" "{\"version\":\"${IMA_SKILL_VERSION:-1.1.7}\"}")"
  node -e "const r=JSON.parse(process.argv[1]); if (r.code && r.code !== 0) { throw new Error('IMA API returned code='+r.code+' msg='+(r.msg||'')); } console.log('[ima] api=reachable')" "$response"
else
  echo "[ima][WARN] credentials not configured; set IMA_OPENAPI_CLIENTID and IMA_OPENAPI_APIKEY from https://ima.qq.com/agent-interface"
fi

echo "[ima] verification complete"
