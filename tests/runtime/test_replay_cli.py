"""Replay CLI tests for the EventStreamRuntime."""

import json

from conftest import (
    _close_test_runtime,
    _load_runtime,
)

from openhands.events.action.replay import ReplayInternalCmdRunAction
from openhands.events.observation.replay import ReplayInternalCmdOutputObservation

# ============================================================================================================================
# Tests
# ============================================================================================================================


def test_initial_analysis(temp_dir, runtime_cls, run_as_openhands):
    runtime = _load_runtime(temp_dir, runtime_cls, run_as_openhands)

    recording_id = '011f1663-6205-4484-b468-5ec471dc5a31'
    prompt = f'Bug in https://app.replay.io/recording/{recording_id}'

    args = dict(prompt=prompt)

    try:
        obs = runtime.run_action(
            ReplayInternalCmdRunAction(
                command_name='initial-analysis',
                command_args=args,
                keep_prompt=False,
                # hidden=True, # hidden basically does not work the way we want it to, so we had to hardcode filtering near the `filter_out` check.
            )
        )
        assert isinstance(
            obs, ReplayInternalCmdOutputObservation
        ), f'Bad observation: {repr(obs)}'

        try:
            result: dict = json.loads(obs.content)
            assert result.get('thisPoint', '') == '78858008544042601258383216576823300'
        except json.JSONDecodeError:
            raise AssertionError(
                f'obs.content should be a valid JSON string: {repr(obs)}'
            )
    finally:
        _close_test_runtime(runtime)
