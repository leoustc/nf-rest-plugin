

#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"
ENV_FILE="${SCRIPT_DIR}/../nf-server/v2/.env"

if [[ -f "$ENV_FILE" ]]; then
  # Load environment variables from the .env file.
  # shellcheck source=/dev/null
  source "$ENV_FILE"
else
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

COMPARTMENT_OCID="${COMPARTMENT_ID:-}"

if [[ -z "$COMPARTMENT_OCID" ]]; then
  echo "COMPARTMENT_ID is not set in $ENV_FILE" >&2
  exit 1
fi

list_instances() {
  oci compute instance list \
    --compartment-id "$COMPARTMENT_OCID" \
    --all \
    --query 'sort_by(
               data[?starts_with("display-name", '"'"'nf-runner'"'"')
                     && contains(['"'"'PROVISIONING'"'"','"'"'RUNNING'"'"','"'"'TERMINATING'"'"','"'"'STOPPING'"'"','"'"'STOPPED'"'"'], "lifecycle-state")],
               &"display-name"
             )[].{
               id:    id,
               name:  "display-name",
               state: "lifecycle-state",
               shape: shape,
               cpu:   "shape-config".ocpus,
               mem:   "shape-config"."memory-in-gbs"
             }' \
    --output json
}

print_table() {
  local json="$1"
  echo "$json" | jq -r '(["index","name","state","shape","cpu","mem"] | @tsv),
                        (to_entries[] | [.key + 1, .value.name, .value.state, .value.shape, .value.cpu, .value.mem] | @tsv)' | \
    column -t
}

terminate_instances() {
  local json="$1"
  local ids=()
  mapfile -t ids < <(echo "$json" | jq -r '.[].id')

  if [[ ${#ids[@]} -eq 0 ]]; then
    echo "No nf-runner instances found to terminate."
    return 0
  fi

  print_table "$json"
  echo "Terminating ${#ids[@]} instance(s) in 5 seconds... (Ctrl+C to cancel)"
  sleep 5

  for id in "${ids[@]}"; do
    echo "Terminating $id"
    oci compute instance terminate --instance-id "$id" --force >/dev/null
  done
}

command="${1:-}"

instances_json="$(list_instances)"

case "$command" in
  display)
    print_table "$instances_json"
    ;;
  kill)
    terminate_instances "$instances_json"
    ;;
  *)
    print_table "$instances_json"
    ;;
esac
