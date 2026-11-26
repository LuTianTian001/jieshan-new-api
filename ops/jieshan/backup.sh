#!/usr/bin/env bash
# Run in a quiet window, with all three services up. No secrets are printed.
set -euo pipefail
cd -- "$(dirname -- "$0")"
umask 077
mkdir -p backups
out=$(mktemp -d "backups/$(date -u +%Y%m%dT%H%M%SZ).XXXXXXXX")
trap 'printf "%s\n" "备份未完成，请勿用 $out 恢复。" >&2' ERR

docker compose exec -T postgres pg_dump -U jieshan -d jieshan_newapi -Fc --no-owner --no-acl > "$out/db.dump"
docker compose exec -T postgres pg_restore --list < "$out/db.dump" > /dev/null
docker compose exec -T new-api tar -C /data -czf - . > "$out/data.tar.gz"
gzip -t "$out/data.tar.gz"
cp -- .env compose.yaml "$out/"
compose_files=(compose.yaml)
if [[ -f compose.override.yaml ]]; then
  cp -- compose.override.yaml "$out/"
  compose_files+=(compose.override.yaml)
fi
for svc in new-api postgres redis; do
  cid=$(docker compose ps -q "$svc")
  image_id=$(docker inspect --format '{{.Image}}' "$cid")
  printf '%s ' "$svc" >> "$out/image-digests.txt"
  docker image inspect --format '{{json .RepoDigests}}' "$image_id" >> "$out/image-digests.txt"
done
(cd -- "$out" && sha256sum db.dump data.tar.gz .env "${compose_files[@]}" image-digests.txt > SHA256SUMS)
touch "$out/COMPLETE"
printf '%s\n' "备份完成：$out（含密钥，异机副本请加密）。"
