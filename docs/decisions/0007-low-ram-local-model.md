# Keep RAM low for the local model

**Context:** Target machines may have as little as 16 GB of RAM shared with other workloads.

**Decision:** Use a short Ollama `keep_alive` so the model unloads between batches, and pick the smallest model that passes the evals.

**Consequences:** Model reloads between batches cost some latency. Model size is set by eval results.
