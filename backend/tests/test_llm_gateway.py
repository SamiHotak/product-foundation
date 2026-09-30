"""The LLM gateway with the real database: plan limits, retries, costs, the llm_calls log,
kill switches, traces - and the AI API + background job built on it."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.plans import DEFAULT_CATALOG
from app.db.session import sync_session
from app.llm.gateway import AiFailedError, AiInputError, AiUnavailableError, LlmGateway
from app.llm.pricing import cost_micro_usd, price_for
from app.llm.providers import ProviderError
from app.llm.samples import SUMMARY_SAMPLES
from app.llm.tasks import Summary
from app.models.billing import UsageRecord
from app.models.llm_call import LlmCall
from app.models.organization import Organization
from app.models.system_flag import Flag, SystemFlag
from app.services.usage import LimitReachedError, month_start
from tests.fakes import ListTracer, ScriptedProvider
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

TEXT = "The shoot is on 14 October at 7:00. The budget of 1,890 EUR is agreed."


def _org() -> uuid.UUID:
    with sync_session() as s:
        org = Organization(name="Test")
        s.add(org)
        s.flush()
        return org.id


def _gateway(
    provider: Any, *, catalog: Any = None, tracer: ListTracer | None = None, **settings: Any
) -> LlmGateway:
    config = get_settings().model_copy(update=settings)
    return LlmGateway(
        config,
        provider,
        sync_session,
        catalog=catalog or DEFAULT_CATALOG,
        tracer=tracer or ListTracer(),
        sleep=lambda _s: None,
    )


def _ai_usage(org: uuid.UUID) -> int:
    with sync_session() as s:
        value = s.scalar(
            select(UsageRecord.count).where(
                UsageRecord.organization_id == org,
                UsageRecord.metric == "ai_requests_per_month",
            )
        )
        return int(value or 0)


def _calls(org: uuid.UUID) -> list[LlmCall]:
    with sync_session() as s:
        return list(s.scalars(select(LlmCall).where(LlmCall.organization_id == org)))


def _err(code: str, retryable: bool, tokens: int = 0) -> ProviderError:
    error = ProviderError(code, f"{code}!", retryable=retryable)
    error.input_tokens = tokens
    return error


def test_a_successful_call_is_counted_priced_logged_and_traced() -> None:
    org, user = _org(), None
    provider, tracer = ScriptedProvider(), ListTracer()
    result = _gateway(provider, tracer=tracer, llm_trace_content=True).run(
        "summarize", TEXT, organization_id=org, user_id=user, metadata={"job_id": "j1"}
    )
    assert isinstance(result.output, Summary)
    luna = price_for("gpt-6-luna")
    assert luna is not None
    expected = cost_micro_usd(luna, input_tokens=1000, cached_input_tokens=200, output_tokens=100)
    assert result.cost_micro_usd == expected and result.attempts == 1
    assert result.model == "gpt-6-luna-2026-08-01"  # the snapshot that answered
    # The model got the data rules and the text wrapped as data.
    _, instructions, user_input = provider.calls[0]
    assert "Security rules" in instructions
    assert user_input.startswith("<user_content>") and TEXT in user_input
    assert _ai_usage(org) == 1
    [call] = _calls(org)
    assert (call.status, call.cost_micro_usd, call.input_tokens) == ("ok", expected, 1000)
    assert call.trace_id == result.trace_id and len(call.trace_id) == 32
    [event] = tracer.events
    assert event.trace_id == result.trace_id and event.input == TEXT
    assert event.cost_usd == expected / 1_000_000 and event.metadata == {"job_id": "j1"}


def test_temporary_errors_are_retried() -> None:
    org = _org()
    provider = ScriptedProvider(_err("rate_limited", True), _err("timeout", True))
    result = _gateway(provider).run("summarize", TEXT, organization_id=org)
    assert result.attempts == 3 and len(provider.calls) == 3
    assert _ai_usage(org) == 1


def test_a_failed_call_is_given_back_unless_tokens_were_billed() -> None:
    org = _org()
    tracer = ListTracer()
    with pytest.raises(AiFailedError):
        _gateway(ScriptedProvider(_err("auth_error", False)), tracer=tracer).run(
            "summarize", TEXT, organization_id=org
        )
    assert _ai_usage(org) == 0  # nothing reached the model: it doesn't count
    [call] = _calls(org)
    assert (call.status, call.error_code, call.attempts) == ("error", "auth_error", 1)
    assert tracer.events[0].status == "auth_error"
    # Retries run out; the last attempt was billed (e.g. a cut-off answer): it counts.
    provider = ScriptedProvider(
        _err("server_error", True), _err("server_error", True), _err("incomplete", True, 500)
    )
    with pytest.raises(AiFailedError):
        _gateway(provider).run("summarize", TEXT, organization_id=org)
    assert _ai_usage(org) == 1
    failed = [c for c in _calls(org) if c.error_code == "incomplete"]
    assert failed and failed[0].input_tokens == 500 and failed[0].cost_micro_usd > 0


def test_answers_that_fail_the_task_check_are_retried_then_refused() -> None:
    org = _org()
    bad = Summary(title="Shoot", key_points=["One."], language="English")
    good = Summary(title="Shoot", key_points=["One."], language="en")
    result = _gateway(ScriptedProvider(bad, good)).run("summarize", TEXT, organization_id=org)
    assert result.output == good and result.attempts == 2
    assert result.input_tokens == 2000  # both attempts were paid for
    with pytest.raises(AiFailedError, match="could not use"):
        _gateway(ScriptedProvider(bad, bad, bad)).run("summarize", TEXT, organization_id=org)
    assert _calls(org)[-1].status == "invalid_output"


def test_plan_limit_stops_before_the_model_is_called() -> None:
    org = _org()
    with sync_session() as s:
        s.execute(
            insert(UsageRecord).values(
                organization_id=org,
                metric="ai_requests_per_month",
                period_start=month_start(datetime.now(UTC)),
                count=50,  # the free plan's limit
            )
        )
    provider = ScriptedProvider()
    with pytest.raises(LimitReachedError) as info:
        _gateway(provider).run("summarize", TEXT, organization_id=org)
    assert info.value.details["metric"] == "ai_requests_per_month"
    assert provider.calls == [] and _calls(org) == []


def test_kill_switches_input_limits_and_no_provider() -> None:
    org = _org()
    provider = ScriptedProvider()
    with pytest.raises(AiUnavailableError, match="not set up"):
        _gateway(provider, llm_enabled=False).run("summarize", TEXT, organization_id=org)
    with pytest.raises(AiUnavailableError, match="not set up"):
        _gateway(None).run("summarize", TEXT, organization_id=org)
    with sync_session() as s:
        s.add(SystemFlag(key=Flag.AI_PAUSED.value, enabled=True))
    with pytest.raises(AiUnavailableError, match="paused"):
        _gateway(provider).run("summarize", TEXT, organization_id=org)
    with sync_session() as s:
        flag = s.get(SystemFlag, Flag.AI_PAUSED.value)
        assert flag is not None
        flag.enabled = False
    with pytest.raises(AiInputError, match="too long"):
        _gateway(provider).run("summarize", "x" * 5001, organization_id=org)
    assert provider.calls == [] and _ai_usage(org) == 0


def test_an_unexpected_error_is_not_retried_and_the_request_is_given_back() -> None:
    org, tracer = _org(), ListTracer()
    provider = ScriptedProvider(ValueError("SDK surprise with user text inside"))
    with pytest.raises(AiFailedError):
        _gateway(provider, tracer=tracer).run("summarize", TEXT, organization_id=org)
    assert len(provider.calls) == 1 and _ai_usage(org) == 0
    [call] = _calls(org)
    assert (call.status, call.error_code) == ("error", "unexpected")
    # Without LLM_TRACE_CONTENT the trace gets the error code, never the error text.
    assert tracer.events[0].error == "unexpected"
    assert "user text" not in str(tracer.events[0])


def test_trace_content_is_off_by_default() -> None:
    assert Settings.model_fields["llm_trace_content"].default is False


def test_trace_content_can_be_switched_off_and_models_changed() -> None:
    org, tracer, provider = _org(), ListTracer(), ScriptedProvider()
    gateway = _gateway(
        provider, tracer=tracer, llm_trace_content=False, llm_models={"summarize": "gpt-6.1-sol"}
    )
    result = gateway.run("summarize", TEXT, organization_id=org)
    assert tracer.events[0].input is None and tracer.events[0].output is None
    assert tracer.events[0].input_tokens == 1000  # numbers are always traced
    assert provider.models == ["gpt-6.1-sol"]  # LLM_MODELS changed the task's model
    assert result.cost_micro_usd > 0


# --- the AI API and the background job --------------------------------------------------


@pytest.fixture
def world() -> World:
    return build_world()


async def test_summary_job_end_to_end(world: World) -> None:
    async with world.client() as c, world.client() as teammate:
        await world.signup_and_verify(c, "owner@example.com")
        await world.invite_and_join(c, teammate, "m@example.com")
        status = (await c.get("/api/ai/status")).json()
        assert status == {
            "available": True,
            "reason": None,
            "provider": "openai",
            "can_use": True,
            "sample_text": SUMMARY_SAMPLES[0],
            "samples_only": False,
        }
        res = await c.post("/api/ai/summaries", json={"text": TEXT})
        assert res.status_code == 202, res.text
        job = res.json()
        assert job["kind"] == "ai_summary" and job["status"] == "queued"
        await world.run_jobs()
        done = (await c.get(f"/api/jobs/{job['id']}")).json()
        assert done["status"] == "done", done
        assert done["result"]["summary"]["language"] == "en"
        assert done["result"]["cost_usd"] > 0 and len(done["result"]["trace_id"]) == 32
        # Private: teammates don't see someone else's AI job.
        assert (await teammate.get(f"/api/jobs/{job['id']}")).status_code == 404
        # Too short / too long texts are refused by the API.
        assert (await c.post("/api/ai/summaries", json={"text": "short"})).status_code == 422
        assert (await c.post("/api/ai/summaries", json={"text": "x" * 5001})).status_code == 422
        usage = {u["metric"]: u for u in (await c.get("/api/billing/current")).json()["usage"]}
        assert usage["ai_requests_per_month"]["used"] == 1


async def test_limit_and_pause_are_shown_at_once(world: World) -> None:
    world.catalog = DEFAULT_CATALOG
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = uuid.UUID(me["active_organization_id"])
        with sync_session() as s:
            s.execute(
                insert(UsageRecord).values(
                    organization_id=org,
                    metric="ai_requests_per_month",
                    period_start=month_start(datetime.now(UTC)),
                    count=50,
                )
            )
        res = await c.post("/api/ai/summaries", json={"text": TEXT})
        assert res.status_code == 402
        assert res.json()["error"]["details"]["metric"] == "ai_requests_per_month"
        with sync_session() as s:
            s.add(SystemFlag(key=Flag.AI_PAUSED.value, enabled=True))
        status = (await c.get("/api/ai/status")).json()
        assert status["available"] is False and "paused" in status["reason"]
        res = await c.post("/api/ai/summaries", json={"text": TEXT})
        assert res.status_code == 503 and res.json()["error"]["code"] == "ai_unavailable"


async def test_a_failing_model_fails_the_job_with_a_safe_message(world: World) -> None:
    world.provider = ScriptedProvider(_err("auth_error", False))
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        job = (await c.post("/api/ai/summaries", json={"text": TEXT})).json()
        await world.run_jobs()
        failed = (await c.get(f"/api/jobs/{job['id']}")).json()
        assert failed["status"] == "failed"
        assert failed["error"] == "The AI service did not answer. Try again in a minute."
        assert "sk-" not in str(failed)


def test_app_errors_have_status_codes() -> None:
    assert AiUnavailableError("x").status_code == 503
    assert AiFailedError("x").status_code == 502
    assert isinstance(AiInputError("x"), AppError) and AiInputError("x").status_code == 400
