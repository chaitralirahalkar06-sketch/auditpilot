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
from .agents.ratio import ratio_agent
from .agents.vendor import vendor_agent


class AuditLeadAgent(BaseAgent):
    """Run intake first and gate all later agents on its tool validations."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
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


specialists = ParallelAgent(
    name="specialists",
    description="Runs the anomaly, vendor, and ratio specialists in parallel.",
    sub_agents=[anomaly_agent, vendor_agent, ratio_agent],
)

audit_lead = AuditLeadAgent(
    name="audit_lead",
    description="Runs intake validation before downstream audit agents.",
    sub_agents=[intake_agent, specialists],
)

root_agent = audit_lead
