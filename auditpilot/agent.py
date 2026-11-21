from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.events.event import Event

from .agents.anomaly import anomaly_agent
from .agents.intake import LOAD_STATUS_KEY
from .agents.intake import TRIAL_BALANCE_STATUS_KEY
from .agents.intake import intake_agent
from .agents.policy import policy_agent
from .agents.ratio import ratio_agent
from .agents.report import report_agent
from .agents.risk import risk_agent
from .agents.skeptic import verification_loop
from .agents.vendor import vendor_agent


class AuditLeadAgent(BaseAgent):
    """Run intake first and gate all later agents on its tool validations."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        memo_status = ctx.session.state.get("audit_memo_status")
        if (
            memo_status in {"DRAFT", "FINAL"}
            and self._is_signoff_request(ctx)
        ):
            async for event in report_agent.run_async(ctx):
                yield event
                if ctx.should_pause_invocation(event):
                    return
            return

        for index, sub_agent in enumerate(self.sub_agents):
            if index > 0 and not self._intake_passed(ctx):
                return
            async for event in sub_agent.run_async(ctx):
                yield event
                if ctx.should_pause_invocation(event):
                    return

    @staticmethod
    def _intake_passed(ctx: InvocationContext) -> bool:
        return (
            ctx.session.state.get(
                f"{LOAD_STATUS_KEY}:{ctx.invocation_id}"
            )
            == "PASSED"
            and ctx.session.state.get(
                f"{TRIAL_BALANCE_STATUS_KEY}:{ctx.invocation_id}"
            )
            == "PASSED"
        )

    @staticmethod
    def _is_signoff_request(ctx: InvocationContext) -> bool:
        if ctx.user_content is None:
            return False
        message = "\n".join(
            part.text
            for part in ctx.user_content.parts or []
            if part.text
        ).strip().upper()
        return message in {"APPROVE", "REQUEST CHANGES", "REJECT"}


specialists = ParallelAgent(
    name="specialists",
    description=(
        "Runs the anomaly, vendor, ratio, and policy specialists in parallel."
    ),
    sub_agents=[anomaly_agent, vendor_agent, ratio_agent, policy_agent],
)

audit_lead = AuditLeadAgent(
    name="audit_lead",
    description=(
        "Runs intake validation, specialists, risk scoring, skeptical "
        "verification, and audit memo generation."
    ),
    sub_agents=[
        intake_agent,
        specialists,
        risk_agent,
        verification_loop,
        report_agent,
    ],
)

root_agent = audit_lead
