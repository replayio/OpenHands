# Copyright 2020-2025 Record Replay Inc.
set -e

if [[ -z "$1" ]]; then
    echo "Usage: $0 <instance-id>"
    exit 1
fi
INSTANCE_ID=$1
PROMPT_NAME="$2"

THIS_DIR="$(dirname "$0")"
OH_ROOT="$THIS_DIR/../.."
OH_ROOT="$(node -e 'console.log(require("path").resolve(process.argv[1]))' $OH_ROOT)"
if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/tmp"
fi
TARGET_FOLDER="$TMP_DIR/bolt/$INSTANCE_ID"
WORKSPACE_ROOT="$TARGET_FOLDER/workspace"
INSTANCE_DIR="$THIS_DIR/$INSTANCE_ID"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo -e "Instance directory \"$INSTANCE_DIR\" not found.\n"
    echo -e "Available instance folders:\n"
    # List all sub folders
    ls -1 -d $THIS_DIR/*/
    echo -e "\n"
    exit 1
fi


# Load prompt.
if [[ -z "$PROMPT_NAME" ]]; then
    PROMPT_NAME="prompt"
fi
PROMPT_FILE="$INSTANCE_DIR/$PROMPT_NAME.md"
if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Prompt file \"$PROMPT_FILE\" not found."
    exit 1
fi
PROMPT=$(cat $PROMPT_FILE)
if [[ -z "$PROMPT" ]]; then
    echo "Prompt file found but was empty."
    exit 1
fi

# (Re-load) source files.
SOURCE_ZIP_FILE="$INSTANCE_DIR/source_code.zip"
rm -rf $WORKSPACE_ROOT
mkdir -p $WORKSPACE_ROOT
if [[ -f "$SOURCE_ZIP_FILE" ]]; then
    unzip -q $SOURCE_ZIP_FILE -d $WORKSPACE_ROOT
    # If it only contains a single folder called "project", move it up.
    if [ -d "$WORKSPACE_ROOT/project" ] && [ $(ls -A "$WORKSPACE_ROOT" | wc -l) -eq 1 ]; then
        mv "$WORKSPACE_ROOT/project"/* "$WORKSPACE_ROOT"
        rm -rf "$WORKSPACE_ROOT/project"
    fi
    pushd $WORKSPACE_ROOT > /dev/null
    git init > /dev/null
    git add -A > /dev/null
    git commit -am "initial commit" > /dev/null
    popd > /dev/null
    echo "Workspace has been set up and git initialized."
else
    echo "Running analysis WITHOUT source code..."
fi

# Config overrides + sanity checks.
export DEBUG=1
# export REPLAY_DEV_MODE=1
export REPLAY_ENABLE_TOOL_CACHE=1
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
LOG_FILE="$TARGET_FOLDER/default.log"
echo "WORKSPACE_ROOT: \"$WORKSPACE_ROOT\""
echo "Logging to \"$LOG_FILE\"..."

# GO.
PROMPT_ONELINE=$(echo "$PROMPT" | tr '\n' " ")
cd $OH_ROOT
set -x
poetry run python -m openhands.core.main -t "$PROMPT_ONELINE" >"${LOG_FILE}" 2>&1
set +x
