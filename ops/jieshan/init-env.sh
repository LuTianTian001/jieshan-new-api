#!/usr/bin/env bash
# Run in the extracted kit on the Linux server. Never prints credentials.
set -euo pipefail
cd -- "$(dirname -- "$0")"
umask 077

if [[ -e .env || -L .env ]]; then
  printf '%s\n' '已有 .env，保留原有密码与密钥。' >&2
  exit 1
fi
command -v openssl >/dev/null || { printf '%s\n' '请安装 openssl 后重试。' >&2; exit 1; }
tmp=$(mktemp .env.tmp.XXXXXXXX)
trap 'rm -f -- "$tmp"' EXIT
pg=$(openssl rand -hex 32)
redis=$(openssl rand -hex 32)
session=$(openssl rand -hex 32)
crypto=$(openssl rand -hex 32)
cat > "$tmp" <<EOF
APP_PORT=13000
PG_PASSWORD=$pg
REDIS_PASSWORD=$redis
SESSION_SECRET=$session
CRYPTO_SECRET=$crypto
# HTTP is only for setup via the SSH tunnel. Change these before enabling a public proxy.
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_TRUSTED_URL=
TRUSTED_PROXIES=none
EOF
# A hard link creates the final name atomically and refuses to overwrite an existing file.
ln -- "$tmp" .env
printf '%s\n' '已生成服务器专用 .env；请保管好，不要提交到 Git。'
