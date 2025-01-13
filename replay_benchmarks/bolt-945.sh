set -ex

export DEBUG=1
export LLM_MODEL="anthropic/claude-3-5-sonnet-20241022"

# TODO: unzip files from replay_benchmarks/bolt-945/source_code.zip to ../workspace

poetry run python -m openhands.core.main -t "TODO: prompt here"
