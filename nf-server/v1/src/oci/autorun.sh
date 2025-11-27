#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR_INPUT="${1:-}"
ACTION="${2:-apply}"
VAR_FILE="${3:-}"
RUN_LOCAL="${RUN_LOCAL:-0}"

run_local_cmd_script() {
  # Only meaningful for apply, skip otherwise.
  if [[ "$ACTION" != "apply" ]]; then
    return 0
  fi
  local script_path="${RUN_DIR_INPUT}/cmd_script.sh"
  echo "=== local cmd_script test ==="
  if [[ ! -f "$script_path" ]]; then
    echo "cmd_script.sh not found in $RUN_DIR_INPUT" >&2
    exit 1
  fi
  echo "Running $script_path"
  bash "$script_path"
  # cd ..
  # rm -rf "$RUN_DIR_INPUT"
  exit 0
}

if [[ -z "$RUN_DIR_INPUT" ]]; then
  echo "RUN_DIR_INPUT (job run directory) is required" >&2
  exit 1
fi

if [[ "$RUN_LOCAL" == "1" ]]; then
  mkdir -p "$RUN_DIR_INPUT"
  cd "$RUN_DIR_INPUT"
  run_local_cmd_script > "$RUN_DIR_INPUT/output-${ACTION}.log" 2> "$RUN_DIR_INPUT/error-${ACTION}.log"
  exit 0
fi

if [[ -z "$VAR_FILE" || ! -f "$VAR_FILE" ]]; then
  echo "Terraform var-file '$VAR_FILE' not found" >&2
  exit 1
fi

mkdir -p "$RUN_DIR_INPUT"
cd "$RUN_DIR_INPUT"

if [[ "$ACTION" == "destroy" ]]; then
  terraform destroy -auto-approve -var-file="$VAR_FILE" || true
  #cd ..
  #rm -rf "$RUN_DIR_INPUT"
else
  {
    # Robust terraform init with a few retries for transient errors
    init_max_retries=3
    init_attempt=1
    while true; do
      if terraform init; then
        break
      fi
      if (( init_attempt >= init_max_retries )); then
        echo "terraform init failed after ${init_attempt} attempts; giving up"
        exit 1
      fi
      echo "terraform init failed on attempt ${init_attempt}, retrying in 30 seconds..."
      init_attempt=$((init_attempt+1))
      sleep 30
    done

    # Retry bootstrap_submit target a few times before failing
    bootstrap_max_retries=3
    bootstrap_attempt=1
    while true; do
      if terraform apply -target=null_resource.bootstrap_submit -auto-approve -var-file="$VAR_FILE"; then
        break
      fi
      if (( bootstrap_attempt >= bootstrap_max_retries )); then
        echo "terraform apply -target=null_resource.bootstrap_submit failed after ${bootstrap_attempt} attempts; giving up"
        exit 1
      fi
      echo "terraform apply -target=null_resource.bootstrap_submit failed on attempt ${bootstrap_attempt}, retrying in 30 seconds..."
      bootstrap_attempt=$((bootstrap_attempt+1))
      terraform destroy -target=null_resource.bootstrap_submit -auto-approve -var-file="$VAR_FILE" || true
      sleep 30
    done

    # Retry the main apply (Ansible/polling) up to 10 times
    max_retries=10
    attempt=1
    while true; do
      if terraform apply -auto-approve -var-file="$VAR_FILE"; then
        break
      fi
      if (( attempt >= max_retries )); then
        echo "terraform apply failed after ${attempt} attempts; giving up"
        exit 1
      fi
      echo "terraform apply failed on attempt ${attempt}, retrying in 30 seconds..."
      attempt=$((attempt+1))
      sleep 30
    done

  } > "$RUN_DIR_INPUT/output-${ACTION}.log" 2> "$RUN_DIR_INPUT/error-${ACTION}.log"
fi

exit 0
