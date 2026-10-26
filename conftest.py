# The bugfix fixture ships failing tests on purpose: the agent benchmark asks
# a model to make them pass. Keep them out of the repository's own test run.
collect_ignore_glob = ["scripts/bench-agents/fixtures/*"]
