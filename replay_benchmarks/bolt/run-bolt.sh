# Copyright 2020-2025 Record Replay Inc.
set -e

if [[ -z "$1" ]]; then
    echo "Usage: $0 <experiment-id>"
    exit 1
fi
EXPERIMENT_ID=$1

THIS_DIR="$(dirname "$0")"
OH_ROOT="$THIS_DIR/.."
OH_ROOT="$(node -e 'console.log(require("path").resolve(process.argv[1]))' $OH_ROOT)"
if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/tmp"
fi
WORKSPACE_ROOT="$TMP_DIR/bolt/workspace/$EXPERIMENT_ID"
EXPERIMENT_DIR="$THIS_DIR/$EXPERIMENT_ID"

if [[ ! -d "$EXPERIMENT_DIR" ]]; then
    echo -e "Experiment directory \"$EXPERIMENT_DIR\" not found.\n"
    echo -e "Available experiment folders:\n"
    # List all sub folders
    ls -1 -d $THIS_DIR/*/
    echo -e "\n"
    exit 1
fi


# Load prompt.
PROMPT=$(cat $EXPERIMENT_DIR/prompt.md)
if [[ -z "$PROMPT" ]]; then
    echo "Prompt file found but was empty."
    exit 1
fi

# (Re-load) source files.
SOURCE_ZIP_FILE="$EXPERIMENT_DIR/source_code.zip"
rm -rf $WORKSPACE_ROOT
mkdir -p $WORKSPACE_ROOT
if [[ -f "$SOURCE_ZIP_FILE" ]]; then
    unzip -q $SOURCE_ZIP_FILE -d $WORKSPACE_ROOT
    echo "Source code extracted to \"$WORKSPACE_ROOT\"."
else
    echo "Running analysis WITHOUT source code..."
fi

# Config overrides + sanity checks.
export DEBUG=1
export REPLAY_DEV_MODE=1
export WORKSPACE_BASE="$WORKSPACE_ROOT"
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
cd $OH_ROOT
poetry run python -m openhands.core.main -t "$PROMPT" \
    > "$LOG_FILE" 2>&1
