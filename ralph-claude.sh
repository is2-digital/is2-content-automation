#!/bin/bash
#
# Ralph loop runner for Claude Code (in Docker sandbox).
# Uses --output-format stream-json for real-time token-level streaming.
# Parses NDJSON events via jq for live display.
#
# Options (env vars):
#   KEEP_JSONL=1    Save raw JSON event log (off by default)
#   PROMPT_FILE=... Path to prompt file (default: ./prompt.md)
#   CLAUDE_BIN=...  Path to claude binary (default: claude)
#
# Requirements: jq (apt-get install jq)
#
# Usage: ./ralph-claude.sh <iterations> <dangerously_skip_permissions>
#        ./ralph-claude.sh 5 on
#        ./ralph-claude.sh 5 off
#        KEEP_JSONL=1 ./ralph-claude.sh 5 on

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
#  $2 = whether to include --dangerously-skip-permissions (default: "on")
if [ -z "${1:-}" ]; then
  echo "Usage: $0 <iterations> [dangerously_skip_permissions]"
  echo "  dangerously_skip_permissions: on | off (default: on)"
  exit 1
fi

ITERATIONS="$1"
SKIP_PERMS_ARG="${2:-on}"

DANGEROUS_FLAG=""
case "$SKIP_PERMS_ARG" in
  on|ON|true|TRUE|1|yes|YES)
    DANGEROUS_FLAG="--dangerously-skip-permissions"
    ;;
  off|OFF|false|FALSE|0|no|NO)
    DANGEROUS_FLAG=""
    ;;
  *)
    echo "ERROR: second argument must be 'on' or 'off' (or true/false, 1/0, yes/no). Got: $SKIP_PERMS_ARG"
    exit 1
    ;;
esac

# --- Preflight Checks ---
echo "Ralph Loop Runner"
echo "  Log (text): $TEXT_LOG"
if [ "$KEEP_JSONL" = "1" ]; then
  echo "  Log (JSON): $LOG_FILE"
fi
echo "  --dangerously-skip-permissions: ${DANGEROUS_FLAG:-<not set>}"
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

# --- Preflight: find Claude CLI even if PATH differs in scripts ---
resolve_claude_bin() {
  # 1) If CLAUDE_BIN is already set and executable, use it
  if [ -n "${CLAUDE_BIN:-}" ] && [ -x "$CLAUDE_BIN" ]; then
    echo "$CLAUDE_BIN"
    return 0
  fi

  # 2) Try PATH (works in interactive shells; may fail in scripts)
  local p
  p="$(command -v claude 2>/dev/null || true)"
  if [ -n "$p" ] && [ -x "$p" ]; then
    echo "$p"
    return 0
  fi

  # 3) Try common Claude Code install locations
  local candidates=(
    "$HOME/.claude/local/claude"
    "$HOME/.local/bin/claude"
    "/usr/local/bin/claude"
    "/usr/bin/claude"
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

FOUND_CLAUDE_BIN="$(resolve_claude_bin || true)"
if [ -z "$FOUND_CLAUDE_BIN" ]; then
  echo "ERROR: Claude CLI not found from this script environment."
  echo "Try re-running with:"
  echo "  CLAUDE_BIN=\"$HOME/.claude/local/claude\" \"$SCRIPT_PATH\" $ITERATIONS $SKIP_PERMS_ARG"
  exit 1
fi

# Use the discovered binary
CLAUDE_BIN="$FOUND_CLAUDE_BIN"

# --- Main Loop ---
for ((i=1; i<=$ITERATIONS; i++)); do
  echo ""
  echo "=========================================="
  echo "  Iteration $i of $ITERATIONS"
  echo "=========================================="
  echo ""

  echo "--- Iteration $i ---" >> "$TEXT_LOG"

  # Run Claude in headless mode with real-time NDJSON streaming.
  #
  # Pipeline: claude → grep (filter noise) → [optional jsonl tee] → jq (extract text) → text log
  #
  if [ "$KEEP_JSONL" = "1" ]; then
    "$CLAUDE_BIN" \
      -p "$(cat "$PROMPT_FILE")" \
      $DANGEROUS_FLAG \
      --output-format stream-json \
      --verbose \
      --include-partial-messages \
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
    "$CLAUDE_BIN" \
      -p "$(cat "$PROMPT_FILE")" \
      $DANGEROUS_FLAG \
      --output-format stream-json \
      --verbose \
      --include-partial-messages \
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
