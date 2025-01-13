set -e

OH_ROOT="$(dirname "$0")/.."
if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/tmp"
fi

REPO=replayio-public/bench-devtools-10609
ISSUE_NUMBER=15
ISSUE_TYPE=issue
COMMENT_ID=2526444494

# Resolver paths.
OH_OUTPUT_DIR="$TMP_DIR/resolver-output"
OH_OUTPUT_FILE="$OH_OUTPUT_DIR/output.jsonl"
WORKSPACE_ROOT="$OH_OUTPUT_DIR/workspace/${ISSUE_TYPE}_${ISSUE_NUMBER}"

# Config overrides + sanity checks.
export DEBUG=1
export LLM_MODEL="anthropic/claude-3-5-sonnet-20241022"
if [[ -z "$LLM_API_KEY" ]]; then
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        echo "LLM_API_KEY or ANTHROPIC_API_KEY environment variable must be set."
        exit 1
    fi
    export LLM_API_KEY=$ANTHROPIC_API_KEY
fi

# Logging.
LOG_FILE="$TMP_DIR/tmp.log"
echo "WORKSPACE_ROOT = $WORKSPACE_ROOT"
echo "Logging to \"$LOG_FILE\"..."

# GO.
rm -f $OH_OUTPUT_FILE
cd "$OH_ROOT"
python -m openhands.resolver.resolve_issue \
    --repo $REPO \
    --issue-number $ISSUE_NUMBER \
    --issue-type $ISSUE_TYPE \
    --max-iterations 50 \
    ${COMMENT_ID:+--comment-id $COMMENT_ID} \
    --output-dir "$OH_OUTPUT_DIR" \
    > "$LOG_FILE" 2>&1
