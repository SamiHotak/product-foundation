"""Evaluate an LLM task on its evaluation set (app/llm/evals/data/<task>.jsonl).

    make eval                                  summarize, pretend model (free, offline)
    make eval ARGS="--live"                    the real model (needs OPENAI_API_KEY; costs cents)
    make eval ARGS="--live --save-baseline"    save the result as the new "before"
    make eval ARGS="--live --model gpt-6.1-sol"  try another model -> before/after table

Each example has checks (right language, facts it must mention, text it must NOT repeat,
number of key points, and the task's own check). The score of an example is the share of
its checks that pass. The run prints a table per example, the totals, and a
before -> after table against the saved baseline (evals/baselines/<task>.json).

Rules (see docs/FILES_AND_AI.md): the data set is for MEASURING, never for tuning the
instructions example by example. Add new examples when real users show a new kind of
problem, then run before and after your change.

Evaluations call the provider directly: no workspace, no plan limit, no llm_calls row.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm import guardrails
from app.llm.pricing import cost_micro_usd, price_for
from app.llm.providers import FakeProvider, LlmProvider, OpenAIProvider, ProviderError
from app.llm.tasks import LlmTask, get_task

HERE = Path(__file__).parent
DATA = HERE / "data"
BASELINES = HERE / "baselines"


@dataclass
class Example:
    """One evaluation example."""

    id: str
    text: str
    expect: dict[str, Any]


@dataclass
class ExampleResult:
    """How the task did on one example."""

    id: str
    score: float
    passed: int
    total: int
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0
    cost_micro_usd: int = 0


@dataclass
class RunResult:
    """A whole evaluation run."""

    task: str
    model: str
    provider: str
    examples: list[ExampleResult]

    @property
    def score(self) -> float:
        """Average example score (0..1)."""
        return sum(e.score for e in self.examples) / len(self.examples) if self.examples else 0.0

    @property
    def fully_passed(self) -> int:
        """Examples with every check passed."""
        return sum(1 for e in self.examples if e.passed == e.total)

    @property
    def cost_usd(self) -> float:
        """What the run cost."""
        return sum(e.cost_micro_usd for e in self.examples) / 1_000_000

    def to_dict(self) -> dict[str, Any]:
        """For the baseline file."""
        return {
            "task": self.task,
            "model": self.model,
            "provider": self.provider,
            "score": round(self.score, 4),
            "fully_passed": self.fully_passed,
            "examples": [asdict(e) for e in self.examples],
        }


def load_examples(task: str, limit: int | None = None) -> list[Example]:
    """Read the task's JSONL file."""
    path = DATA / f"{task}.jsonl"
    if not path.exists():
        raise SystemExit(f"No evaluation set for {task!r}: create {path}")
    examples = [
        Example(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return examples[:limit] if limit else examples


def _text_of(output: BaseModel) -> str:
    return json.dumps(output.model_dump(), ensure_ascii=False).lower()


def score_output(
    task: LlmTask, output: BaseModel, expect: dict[str, Any]
) -> tuple[int, int, list[str]]:
    """(passed, total, failures) for one answer. Works for any task with these keys."""
    checks: list[tuple[str, bool]] = []
    data = output.model_dump()
    if "language" in expect:
        checks.append(
            (f"language {expect['language']}", data.get("language") == expect["language"])
        )
    text = _text_of(output)
    for phrase in expect.get("must_mention", []):
        checks.append((f"mentions {phrase!r}", phrase.lower() in text))
    for phrase in expect.get("must_not_mention", []):
        checks.append((f"does not mention {phrase!r}", phrase.lower() not in text))
    points = data.get("key_points")
    if isinstance(points, list):
        low, high = expect.get("min_points", 1), expect.get("max_points", 10)
        checks.append((f"{low}-{high} key points", low <= len(points) <= high))
    if task.check is not None:
        problem = task.check(output)
        checks.append((f"task check ({problem or 'ok'})", problem is None))
    failures = [name for name, ok in checks if not ok]
    return len(checks) - len(failures), len(checks), failures


def run_eval(
    task: LlmTask, provider: LlmProvider, examples: list[Example], *, retries: int = 2
) -> RunResult:
    """Run every example once (temporary errors are retried) and score it."""
    results = []
    instructions = guardrails.instructions(task.instructions)
    for example in examples:
        started = time.perf_counter()
        cost = 0
        try:
            user_input = guardrails.untrusted(example.text, max_chars=task.max_input_chars)
            for attempt in range(retries + 1):
                try:
                    answer = provider.complete(task, instructions, user_input)
                    break
                except ProviderError as exc:
                    if not exc.retryable or attempt == retries:
                        raise
                    time.sleep(exc.retry_after or 2.0 * (attempt + 1))
            price = price_for(answer.model) or price_for(task.model)
            if price:
                cost = cost_micro_usd(
                    price,
                    input_tokens=answer.input_tokens,
                    cached_input_tokens=answer.cached_input_tokens,
                    output_tokens=answer.output_tokens,
                )
            passed, total, failures = score_output(task, answer.output, example.expect)
        except (ProviderError, guardrails.InputTooLongError) as exc:
            passed, total, failures = 0, 1, [f"no answer: {exc}"[:200]]
        results.append(
            ExampleResult(
                id=example.id,
                score=passed / total,
                passed=passed,
                total=total,
                failures=failures,
                latency_ms=round((time.perf_counter() - started) * 1000),
                cost_micro_usd=cost,
            )
        )
    return RunResult(task=task.name, model=task.model, provider=provider.name, examples=results)


def report(result: RunResult, baseline: dict[str, Any] | None) -> str:
    """Markdown tables: per example, totals, and before -> after."""
    lines = [
        f"## Eval: {result.task} ({result.provider}, model {result.model})",
        "",
        "| Example | Score | Failed checks | ms |",
        "|---|---|---|---|",
    ]
    for e in result.examples:
        failed = "; ".join(e.failures) or "-"
        lines.append(f"| {e.id} | {e.passed}/{e.total} | {failed} | {e.latency_ms} |")
    lines += [
        "",
        f"**Score {result.score:.1%}**, {result.fully_passed}/{len(result.examples)} examples "
        f"fully passed, cost ${result.cost_usd:.4f}",
    ]
    if baseline:
        before = {e["id"]: e for e in baseline.get("examples", [])}
        lines += [
            "",
            f"### Before -> after (before: {baseline.get('provider')}, "
            f"model {baseline.get('model')})",
            "",
            "| | Before | After |",
            "|---|---|---|",
            f"| Score | {baseline.get('score', 0):.1%} | {result.score:.1%} |",
            f"| Fully passed | {baseline.get('fully_passed', 0)}/{len(before)} | "
            f"{result.fully_passed}/{len(result.examples)} |",
        ]
        changed = [
            f"| {e.id} | {before[e.id]['passed']}/{before[e.id]['total']} | {e.passed}/{e.total} |"
            for e in result.examples
            if e.id in before and before[e.id]["passed"] != e.passed
        ]
        if changed:
            lines += ["", "| Changed example | Before | After |", "|---|---|---|", *changed]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Exit code 1 when the score is below --min-score."""
    parser = argparse.ArgumentParser(description="Evaluate an LLM task.")
    parser.add_argument("--task", default="summarize")
    parser.add_argument("--live", action="store_true", help="use the real model (OPENAI_API_KEY)")
    parser.add_argument("--model", help="try another model (default: the task's model)")
    parser.add_argument("--limit", type=int, help="only the first N examples")
    parser.add_argument("--min-score", type=float, default=0.0, help="fail below this (0..1)")
    parser.add_argument("--save-baseline", action="store_true", help="save as the new 'before'")
    args = parser.parse_args(argv)

    settings = get_settings()
    overrides = {args.task: args.model} if args.model else settings.llm_models
    task = get_task(args.task, overrides)
    provider: LlmProvider
    if args.live:
        if not settings.openai_enabled:
            print("OPENAI_API_KEY is not set: can't run --live.", file=sys.stderr)
            return 2
        assert settings.openai_api_key is not None
        provider = OpenAIProvider(
            settings.openai_api_key.get_secret_value(), settings.openai_base_url
        )
    else:
        provider = FakeProvider(delay_seconds=0)
    result = run_eval(task, provider, load_examples(args.task, args.limit))
    baseline_path = BASELINES / f"{args.task}.json"
    baseline = json.loads(baseline_path.read_text("utf-8")) if baseline_path.exists() else None
    print(report(result, baseline))
    if args.save_baseline:
        BASELINES.mkdir(exist_ok=True)
        baseline_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n")
        print(f"\nSaved as the new baseline: {baseline_path}")
    if result.score < args.min_score:
        print(f"\nFAILED: score {result.score:.1%} is below {args.min_score:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
