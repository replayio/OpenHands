set -e

OH_DIR="$(dirname "$0")/.."
if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/tmp"
fi

export DEBUG=1
export LLM_MODEL="anthropic/claude-3-5-sonnet-20241022"
REPO=replayio-public/bench-devtools-10608
ISSUE_NUMBER=2
ISSUE_TYPE=issue
COMMENT_ID=""
LOG_FILE="$TMP_DIR/tmp.log"

OH_OUTPUT_DIR="$TMP_DIR/resolver-output"
OH_OUTPUT_FILE="$OH_OUTPUT_DIR/output.jsonl"

if [[ -z "$LLM_API_KEY" ]]; then
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        echo "LLM_API_KEY or ANTHROPIC_API_KEY environment variable must be set."
        exit 1
    fi
    export LLM_API_KEY=$ANTHROPIC_API_KEY
fi

TARGET_REPO="$OH_OUTPUT_DIR/workspace/${ISSUE_TYPE}_${ISSUE_NUMBER}"

rm -f $OH_OUTPUT_FILE

echo "Target repo at: $TARGET_REPO"
echo "Logging to \"$LOG_FILE\"..."

cd "$OH_DIR"

python -m openhands.resolver.resolve_issue \
    --repo $REPO \
    --issue-number $ISSUE_NUMBER \
    --issue-type $ISSUE_TYPE \
    --max-iterations 50 \
    ${COMMENT_ID:+--comment-id $COMMENT_ID} \
    --output-dir "$OH_OUTPUT_DIR" \
    > "$LOG_FILE" 2>&1
