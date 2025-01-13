set -e

thisDir="$(dirname "$0")"
OH_ROOT="$thisDir/.."
OH_ROOT="$(node -e 'console.log(require("path").resolve(process.argv[1]))' $OH_ROOT)"
if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/tmp"
fi

WORKSPACE_ROOT="$TMP_DIR/workspace/bolt-945"
SOURCE_ZIP_FILE="$OH_ROOT/replay_benchmarks/bolt-945/source_code.zip"

# Override the source code files into the workspace.
rm -rf $WORKSPACE_ROOT
mkdir -p $WORKSPACE_ROOT
unzip -q $SOURCE_ZIP_FILE -d $WORKSPACE_ROOT

# Config overrides + sanity checks.
export DEBUG=1
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
poetry run python -m openhands.core.main -t "list all files in the workspace"
