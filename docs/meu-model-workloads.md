# Models by workload

Meu can use explicitly selected providers for four roles: light tasks, complex tasks,
web research, and images/screenshots. Each provider needs its own saved credentials.
For example, use Z.ai for light tasks, DeepSeek for complex tasks, and Gemini for web
or images. No subscription, benchmark ranking or model name automatically authorizes
another provider.

In Windows, open Settings > Model > Main model > Models by workload. Choose the
provider and exact model for each role, save, and start an Auto chat. Saving enabled
workload models selects Meu Coordinator General for new sessions. In autonomous
Android, open the local Meu setup, save each provider key, enable Models by workload,
and choose the roles before starting the engine. Existing same-provider Auto remains
available when workload routing is not configured. Existing sessions keep their saved
model configuration; use the chat model picker to switch to Auto.

Main-agent routing is local: the latest substantive request selects light/complex or
web without an extra classifier API call. This is a heuristic, not a benchmark or a
guarantee of perfect complexity assessment. The General Coordinator also classifies
its helper tasks and obeys the explicit roles. Attached images select the image role;
vision analysis tools use the same configured image model during the turn. Known
text-only image models are rejected. A web role selects an LLM for research; it does
not itself replace or pay for a search/extraction service. Web helpers are limited to
search, extraction and reading, subject to the parent's tool restrictions.

Only configured providers are used for these routes; missing credentials or an
unavailable chosen provider are reported instead of silently billing another provider.
Credentials resolve through the existing per-provider resolver, not through the main
model's key. Routing does not rewrite historical messages or the system prompt.
A provider change still has its own cache and may require resending conversation
context to that explicitly selected provider.

Validation covers actual SDK request bodies with a mock HTTP transport, complete
local-provider turns, restoration after errors, credential separation, model selection,
helper restrictions, and settings persistence. Live provider inference and physical
Android behaviour require a separate device trial; an image reaching the API does
not prove that a particular model interpreted its contents correctly.
