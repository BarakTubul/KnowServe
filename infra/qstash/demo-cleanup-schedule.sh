#!/usr/bin/env bash
# One daily QStash schedule for the Demo cleanup (OPEN-26 N4, ADR 0006).
#
# REQUIRES OWNER APPROVAL BEFORE IT IS RUN WITH QSTASH_SEND=yes. It creates cloud state in Upstash.
# Nothing in this repository runs it. Read infra/qstash/README.md first.
#
#   usage:  demo-cleanup-schedule.sh check | create | show | delete
#
# The default is a DRY RUN: the request is printed (token redacted) and nothing is sent. Set
# QSTASH_SEND=yes to send. The token is read from the environment only (never from an argument,
# never printed, and passed to curl on stdin so it does not appear in the process list).
#
#   QSTASH_TOKEN         required to send. Upstash console token for the same region as KS_QSTASH_URL.
#   KS_QSTASH_URL        required: region-specific base URL, e.g. https://qstash-eu-central-1.upstash.io
#   WORKER_PUBLIC_URL    required: exactly the Worker's KS_WORKER_PUBLIC_URL (https, no trailing slash).
#                        QStash signs the delivery for this exact URL and the Worker verifies it.
#   SCHEDULE_CRON        default "CRON_TZ=UTC 0 3 * * *" (03:00 UTC daily).
#   SCHEDULE_ID          default "knowserve-demo-cleanup" (fixed id: re-running create updates the
#                        same schedule instead of adding a second one; see README, unverified).
#
# The request has no body and no query parameters on purpose: the endpoint accepts none.
set -euo pipefail

cmd="${1:-}"
send="${QSTASH_SEND:-no}"
base="${KS_QSTASH_URL:-}"
worker="${WORKER_PUBLIC_URL:-}"
cron="${SCHEDULE_CRON:-CRON_TZ=UTC 0 3 * * *}"
sid="${SCHEDULE_ID:-knowserve-demo-cleanup}"
path="/internal/maintenance/demo-cleanup"

die() { echo "error: $*" >&2; exit 2; }

[ -n "$base" ] || die "KS_QSTASH_URL is required (region-specific; the US default rejects EU tokens)."
case "$base" in https://*) ;; *) die "KS_QSTASH_URL must be https://." ;; esac
base="${base%/}"

case "$cmd" in
  check|show|delete|create) ;;
  *) die "usage: $0 check|create|show|delete" ;;
esac

if [ "$cmd" = "create" ]; then
  [ -n "$worker" ] || die "WORKER_PUBLIC_URL is required."
  case "$worker" in https://*) ;; *) die "WORKER_PUBLIC_URL must be https://." ;; esac
  case "$worker" in */) die "WORKER_PUBLIC_URL must not end with a slash." ;; esac
  case "$worker" in *\?*|*\#*) die "WORKER_PUBLIC_URL must not contain a query or fragment." ;; esac
fi

# Build the request: method, url, extra headers.
headers=()
case "$cmd" in
  check)  method=GET;    url="$base/v2/schedules" ;;
  show)   method=GET;    url="$base/v2/schedules/$sid" ;;
  delete) method=DELETE; url="$base/v2/schedules/$sid" ;;
  create)
    method=POST
    url="$base/v2/schedules/${worker}${path}"
    headers+=("Upstash-Cron: ${cron}" "Upstash-Method: POST" "Upstash-Schedule-Id: ${sid}")
    ;;
esac

echo "request: $method $url"
for h in "${headers[@]+"${headers[@]}"}"; do echo "header:  $h"; done
echo "header:  Authorization: Bearer <redacted>"
echo "body:    (none)"

if [ "$send" != "yes" ]; then
  echo "DRY RUN: nothing was sent. Set QSTASH_SEND=yes (after Owner approval) to send."
  exit 0
fi

[ -n "${QSTASH_TOKEN:-}" ] || die "QSTASH_TOKEN is required to send."
if [ "$cmd" = "create" ] || [ "$cmd" = "delete" ]; then
  [ "${OWNER_APPROVED:-}" = "yes" ] || die "create/delete need OWNER_APPROVED=yes (record the approval first)."
fi

# curl reads its config from stdin, so the token is not visible in the process list.
{
  printf 'header = "Authorization: Bearer %s"\n' "$QSTASH_TOKEN"
  for h in "${headers[@]+"${headers[@]}"}"; do printf 'header = "%s"\n' "$h"; done
} | curl --silent --show-error --fail-with-body --max-time 30 --request "$method" --config - "$url"
echo
