## ADDED Requirements

### Requirement: Provider-agnostic LLM client protocol

The system SHALL define a `LlmClient` typing Protocol in `hbot/controllers/research/llm_client.py` with two methods:
- `chat(messages: list[dict[str, str]], temperature: float = 0.7) -> str` — sends a list of message dicts (`{"role": ..., "content": ...}`) to the LLM and returns the assistant's response text.
- `count_tokens(text: str) -> int` — returns an approximate token count for the given text.

The protocol SHALL also expose a `tokens_used: int` attribute tracking cumulative token consumption across all calls.

#### Scenario: Protocol is structural, not nominal
- **WHEN** a class implements `chat()`, `count_tokens()`, and `tokens_used`
- **THEN** it satisfies the `LlmClient` protocol without explicit inheritance

#### Scenario: Mock injection for testing
- **WHEN** a test provides a mock object with `chat()`, `count_tokens()`, and `tokens_used`
- **THEN** it SHALL be accepted wherever `LlmClient` is expected

### Requirement: Anthropic client implementation

The system SHALL provide an `AnthropicClient` class that implements `LlmClient` by wrapping the `anthropic` SDK.

- `chat()` SHALL call `anthropic.Anthropic().messages.create()` with the resolved model.
- The API key SHALL be resolved via three-tier lookup: `ANTHROPIC_API_KEY` → `RESEARCH_LLM_API_KEY` → `LLM_API_KEY`. The first non-empty value wins.
- The model SHALL be resolved via: `ANTHROPIC_MODEL` → `RESEARCH_LLM_MODEL` → hardcoded default `claude-sonnet-4-20250514`.
- After each `chat()` call, `tokens_used` SHALL be incremented by the sum of input and output tokens reported by the API response.
- `count_tokens()` SHALL return `len(text) // 4` as an approximation.

#### Scenario: Successful chat call
- **WHEN** `AnthropicClient.chat([{"role": "user", "content": "hello"}])` is called
- **THEN** the Anthropic API is called with the configured model and the response text content is returned

#### Scenario: Missing API key (all tiers)
- **WHEN** none of `ANTHROPIC_API_KEY`, `RESEARCH_LLM_API_KEY`, or `LLM_API_KEY` are set
- **THEN** `build_client("anthropic")` SHALL raise `EnvironmentError` with a message listing all checked variable names

#### Scenario: Fallback key resolution
- **WHEN** `ANTHROPIC_API_KEY` is not set but `RESEARCH_LLM_API_KEY` is set
- **THEN** `build_client("anthropic")` uses the `RESEARCH_LLM_API_KEY` value

#### Scenario: Token accumulation
- **WHEN** two `chat()` calls are made, the first using 100 tokens and the second using 150 tokens
- **THEN** `tokens_used` SHALL equal 250

### Requirement: OpenAI client implementation

The system SHALL provide an `OpenAIClient` class that implements `LlmClient` by wrapping the `openai` SDK.

- `chat()` SHALL call `openai.OpenAI().chat.completions.create()` with the resolved model.
- The API key SHALL be resolved via three-tier lookup: `OPENAI_API_KEY` → `RESEARCH_LLM_API_KEY` → `LLM_API_KEY`. The first non-empty value wins.
- The model SHALL be resolved via: `OPENAI_MODEL` → `RESEARCH_LLM_MODEL` → hardcoded default `gpt-4o`.
- After each `chat()` call, `tokens_used` SHALL be incremented by the total tokens reported by the API response.
- `count_tokens()` SHALL return `len(text) // 4` as an approximation.

#### Scenario: Successful chat call
- **WHEN** `OpenAIClient.chat([{"role": "user", "content": "hello"}])` is called
- **THEN** the OpenAI API is called with the configured model and the response message content is returned

#### Scenario: Missing API key (all tiers)
- **WHEN** none of `OPENAI_API_KEY`, `RESEARCH_LLM_API_KEY`, or `LLM_API_KEY` are set
- **THEN** `build_client("openai")` SHALL raise `EnvironmentError` with a message listing all checked variable names

### Requirement: Client factory

The system SHALL provide a `build_client(provider: str) -> LlmClient` factory function.

- If `provider` is `"anthropic"`, it SHALL return an `AnthropicClient` instance.
- If `provider` is `"openai"`, it SHALL return an `OpenAIClient` instance.
- If `provider` is any other string, it SHALL raise `ValueError` listing the supported providers.
- If no API key is found after the three-tier lookup for the chosen provider, it SHALL raise `EnvironmentError`.

#### Scenario: Valid provider selection
- **WHEN** `build_client("anthropic")` is called with at least one of the three API key env vars set
- **THEN** an `AnthropicClient` instance is returned

#### Scenario: Unknown provider
- **WHEN** `build_client("gemini")` is called
- **THEN** `ValueError` is raised with message containing `"anthropic"` and `"openai"` as valid options

### Requirement: No SDK imports outside this module

Only `hbot/controllers/research/llm_client.py` SHALL import `anthropic` or `openai` packages. All other modules in the exploration agent SHALL depend on the `LlmClient` protocol, not concrete client classes.

#### Scenario: Import isolation
- **WHEN** `exploration_session.py` type-hints an LLM dependency
- **THEN** it SHALL reference `LlmClient`, not `AnthropicClient` or `OpenAIClient`
