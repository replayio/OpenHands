enum ObservationType {
  // The contents of a file
  READ = "read",

  // The HTML contents of a URL
  BROWSE = "browse",

  // The output of a command
  RUN = "run",

  // The output of an IPython command
  RUN_IPYTHON = "run_ipython",

  // The output of an internal replay command
  RUN_REPLAY_INTERNAL = "run_replay_internal",

  // The output of a tool replay command
  RUN_REPLAY_TOOL = "run_replay_tool",

  // A message from the user
  CHAT = "chat",

  // Agent state has changed
  AGENT_STATE_CHANGED = "agent_state_changed",

  // Delegate result
  DELEGATE = "delegate",
}

export default ObservationType;
