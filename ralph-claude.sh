#!/bin/bash
#
# Ralph loop runner for Claude Code or Amp (in Docker sandbox).
# Uses --output-format stream-json for real-time token-level streaming.
# Parses NDJSON events via jq for live display.
#
# Options (env vars):
#   KEEP_JSONL=1    Save raw JSON event log (off by default)
#   PROMPT_FILE=... Path to prompt file (default: ./prompt.md)
#   CLAUDE_BIN=...  Path to tool binary (default: auto-detect)
#
# Requirements: jq (apt-get install jq)
#
# Usage: ./ralph-claude.sh <iterations> <tool> [dangerously_skip_permissions]
#        ./ralph-claude.sh 5 claude on
#        ./ralph-claude.sh 5 amp
#        KEEP_JSONL=1 ./ralph-claude.sh 5 claude on

# --- Configuration ---
TIMESTAMP=$(TZ="America/Los_Angeles" date +"%Y%m%d_%H%M%S")
LOG_DIR=".ralph-logs"
mkdir -p "$LOG_DIR"
TEXT_LOG="${LOG_DIR}/ralph_session_${TIMESTAMP}.md"
KEEP_JSONL="${KEEP_JSONL:-0}"  # Set KEEP_JSONL=1 to save raw JSON event log

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROMPT_FILE="${PROMPT_FILE:-${SCRIPT_DIR}/prompt.md}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

if [ "$KEEP_JSONL" = "1" ]; then
  LOG_FILE="${LOG_DIR}/claude_session_${TIMESTAMP}.jsonl"
fi

# --- Required args ---
#  $1 = iterations (required)
#  $2 = tool name (required): claude | amp
#  $3 = whether to include --dangerously-skip-permissions (default: "on", claude only)
if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
  echo "Usage: $0 <iterations> <tool> [dangerously_skip_permissions]"
  echo "  tool: claude | amp"
  echo "  dangerously_skip_permissions: on | off (default: on, claude only)"
  exit 1
fi

ITERATIONS="$1"
TOOL_NAME="$2"

case "$TOOL_NAME" in
  claude)
    ;;
  amp)
    ;;
  *)
    echo "ERROR: tool must be 'claude' or 'amp'. Got: $TOOL_NAME"
    exit 1
    ;;
esac

SKIP_PERMS_ARG="${3:-on}"

DANGEROUS_FLAG=""
if [ "$TOOL_NAME" = "claude" ]; then
  case "$SKIP_PERMS_ARG" in
    on|ON|true|TRUE|1|yes|YES)
      DANGEROUS_FLAG="--dangerously-skip-permissions"
      ;;
    off|OFF|false|FALSE|0|no|NO)
      DANGEROUS_FLAG=""
      ;;
    *)
      echo "ERROR: third argument must be 'on' or 'off' (or true/false, 1/0, yes/no). Got: $SKIP_PERMS_ARG"
      exit 1
      ;;
  esac
fi

# --- Preflight Checks ---
echo "Ralph Loop Runner"
echo "  Tool: $TOOL_NAME"
echo "  Log (text): $TEXT_LOG"
if [ "$KEEP_JSONL" = "1" ]; then
  echo "  Log (JSON): $LOG_FILE"
fi
if [ "$TOOL_NAME" = "claude" ]; then
  echo "  --dangerously-skip-permissions: ${DANGEROUS_FLAG:-<not set>}"
fi
echo ""

if [ ! -f "$PROMPT_FILE" ]; then
  echo "ERROR: Prompt file not found: $PROMPT_FILE"
  exit 1
fi

if ! command -v jq &> /dev/null; then
  echo "ERROR: 'jq' is required but was not found."
  echo "Install with: sudo apt-get install -y jq"
  exit 1
fi

# --- Preflight: Docker containers must be running ---
# Claude runs in a sandbox that cannot read .env, so it cannot run `make dev`.
# Containers must already be up before starting the session.
REQUIRED_CONTAINERS=("ica-app-1" "ica-postgres-1" "ica-redis-1")
MISSING_CONTAINERS=()

for cname in "${REQUIRED_CONTAINERS[@]}"; do
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
    MISSING_CONTAINERS+=("$cname")
  fi
done

if [ ${#MISSING_CONTAINERS[@]} -gt 0 ]; then
  echo "ERROR: Required Docker containers are not running:"
  for c in "${MISSING_CONTAINERS[@]}"; do
    echo "  - $c"
  done
  echo ""
  echo "Start them first with:  make dev"
  echo "(Run in a separate terminal — it stays in the foreground.)"
  exit 1
fi
echo "  Docker containers: all running"

# --- Preflight: find tool CLI even if PATH differs in scripts ---
resolve_tool_bin() {
  local tool_name="$1"
  local env_bin_var="${2:-}"

  # 1) If env var override is set and executable, use it
  if [ -n "$env_bin_var" ] && [ -x "$env_bin_var" ]; then
    echo "$env_bin_var"
    return 0
  fi

  # 2) Try PATH (works in interactive shells; may fail in scripts)
  local p
  p="$(command -v "$tool_name" 2>/dev/null || true)"
  if [ -n "$p" ] && [ -x "$p" ]; then
    echo "$p"
    return 0
  fi

  # 3) Try common install locations
  local candidates=(
    "$HOME/.${tool_name}/local/${tool_name}"
    "$HOME/.local/bin/${tool_name}"
    "/usr/local/bin/${tool_name}"
    "/usr/bin/${tool_name}"
  )

  local c
  for c in "${candidates[@]}"; do
    if [ -x "$c" ]; then
      echo "$c"
      return 0
    fi
  done

  return 1
}

SCRIPT_PATH="$(cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")"

FOUND_TOOL_BIN="$(resolve_tool_bin "$TOOL_NAME" "${CLAUDE_BIN:-}" || true)"
if [ -z "$FOUND_TOOL_BIN" ]; then
  echo "ERROR: ${TOOL_NAME} CLI not found from this script environment."
  echo "Try re-running with:"
  echo "  CLAUDE_BIN=\"/path/to/${TOOL_NAME}\" \"$SCRIPT_PATH\" $ITERATIONS $TOOL_NAME $SKIP_PERMS_ARG"
  exit 1
fi

# Use the discovered binary
TOOL_BIN="$FOUND_TOOL_BIN"

# --- Main Loop ---
for ((i=1; i<=$ITERATIONS; i++)); do
  echo ""
  echo "=========================================="
  echo "  Iteration $i of $ITERATIONS"
  echo "=========================================="
  echo ""

  echo "--- Iteration $i ---" >> "$TEXT_LOG"

  # Build tool-specific command arguments
  if [ "$TOOL_NAME" = "claude" ]; then
    TOOL_PROMPT_FLAG="-p"
    TOOL_EXTRA_FLAGS="$DANGEROUS_FLAG --output-format stream-json --verbose --include-partial-messages"
  else
    # amp uses -x for prompt execution
    TOOL_PROMPT_FLAG="-x"
    TOOL_EXTRA_FLAGS="--output-format stream-json --verbose --include-partial-messages"
  fi

  # Run tool in headless mode with real-time NDJSON streaming.
  #
  # Pipeline: tool → grep (filter noise) → [optional jsonl tee] → jq (extract text) → text log
  #
  if [ "$KEEP_JSONL" = "1" ]; then
    "$TOOL_BIN" \
      $TOOL_PROMPT_FLAG "$(cat "$PROMPT_FILE")" \
      $TOOL_EXTRA_FLAGS \
      2>&1 \
      | grep --line-buffered '^{' \
      | tee -a "$LOG_FILE" \
      | jq --unbuffered -rj '
          if .type == "stream_event" and .event.type? == "content_block_delta" and .event.delta.type? == "text_delta" then
            .event.delta.text
          elif .type == "stream_event" and .event.type? == "content_block_stop" then
            "\n"
          else
            empty
          end
        ' \
      | tee -a "$TEXT_LOG"
  else
    "$TOOL_BIN" \
      $TOOL_PROMPT_FLAG "$(cat "$PROMPT_FILE")" \
      $TOOL_EXTRA_FLAGS \
      2>&1 \
      | grep --line-buffered '^{' \
      | jq --unbuffered -rj '
          if .type == "stream_event" and .event.type? == "content_block_delta" and .event.delta.type? == "text_delta" then
            .event.delta.text
          elif .type == "stream_event" and .event.type? == "content_block_stop" then
            "\n"
          else
            empty
          end
        ' \
      | tee -a "$TEXT_LOG"
  fi

  echo "" | tee -a "$TEXT_LOG"
  echo "--- End of iteration $i ---" >> "$TEXT_LOG"

  # Check for the completion marker
  if grep -q "<promise>COMPLETE</promise>" "$TEXT_LOG" 2>/dev/null; then
    echo ""
    msg="All tasks complete after $i iterations."
    echo "$msg" | tee -a "$TEXT_LOG"
    exit 0
  fi

done

echo ""
echo "Reached max iterations ($ITERATIONS)" | tee -a "$TEXT_LOG"
exit 1
