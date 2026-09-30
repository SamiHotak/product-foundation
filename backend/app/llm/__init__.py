"""LLM gateway: the one place where every LLM call happens.

- tasks.py       what we ask a model to do (model, instructions, output schema, limits)
- guardrails.py  user content is data, never instructions; input size limits
- providers.py   OpenAI (Responses API + Structured Outputs) and a pretend model for dev
- gateway.py     kill switches, plan limits, retries, cost accounting, the llm_calls log
- pricing.py     USD per 1M tokens per model
- tracing.py     traces to Langfuse (OpenTelemetry), sent by the worker
- evals/         evaluation sets and the runner (`make eval`)

See docs/FILES_AND_AI.md.
"""
