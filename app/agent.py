# ruff: noqa
import datetime
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent, Context
from google.adk.apps import App
from google.adk.tools import AgentTool
from google.adk.workflow import Workflow, node, FunctionNode, START
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.genai import types

# MCP imports
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .config import config

# --- 1. State Schema ---
class Subscription(BaseModel):
    name: str
    cost: float
    billing_cycle: str  # "monthly" or "yearly"
    status: str  # "active" or "cancelled"

class FinFitState(BaseModel):
    subscriptions: List[Subscription] = Field(default_factory=lambda: [
        Subscription(name="Netflix", cost=15.49, billing_cycle="monthly", status="active"),
        Subscription(name="Spotify", cost=10.99, billing_cycle="monthly", status="active"),
        Subscription(name="Gym", cost=50.00, billing_cycle="monthly", status="active"),
        Subscription(name="Adobe CC", cost=54.99, billing_cycle="monthly", status="active"),
        Subscription(name="Amazon Prime", cost=139.00, billing_cycle="yearly", status="active"),
    ])
    security_audit_logs: List[Dict[str, Any]] = Field(default_factory=list)
    scrubbed_query: str = ""
    last_orchestrator_output: Dict[str, Any] = Field(default_factory=dict)

# --- 2. Orchestrator Output Schema ---
class OrchestratorOutput(BaseModel):
    response: str = Field(description="The message to display to the user, summarizing the response or findings.")
    needs_confirmation: bool = Field(description="True if the user requests to cancel a subscription or apply a savings plan, which requires confirmation.")
    action_type: Optional[str] = Field(None, description="The type of action: 'cancel_subscription' or 'apply_savings'.")
    action_target: Optional[str] = Field(None, description="The target subscription name or savings target name.")

# --- 3. MCP Toolset Setup ---
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"]
        )
    )
)

# --- 4. Sub-Agents ---
subscription_agent = LlmAgent(
    name="subscription_agent",
    model=config.model,
    instruction=(
        "You are a subscription specialist. You help the user inspect their active subscriptions, "
        "calculate total monthly expenses, and flag high-cost subscriptions.\n"
        "State data contains a list of subscriptions: {subscriptions}.\n"
        "Use the tools provided by the MCP server (such as list_mock_subscriptions and get_subscription_details) "
        "to fetch details and analyze them (e.g., usage score, last used date).\n"
        "If the user wants to cancel a subscription, output the specific subscription name."
    ),
    tools=[mcp_toolset]
)

savings_agent = LlmAgent(
    name="savings_agent",
    model=config.model,
    instruction=(
        "You are a savings and budget specialist. You review the user's spending habits and "
        "subscriptions to generate custom saving strategies, monthly budget targets, and practical cost-cutting tips.\n"
        "Active subscriptions state: {subscriptions}.\n"
        "Use the tools provided by the MCP server (such as estimate_upcoming_bills and generate_savings_calculator) "
        "to calculate target budgets and analyze upcoming bills.\n"
        "Propose concrete monthly saving goals and budget adjustments."
    ),
    tools=[mcp_toolset]
)

# --- 5. Orchestrator Agent ---
orchestrator_agent = LlmAgent(
    name="orchestrator",
    model=config.model,
    instruction=(
        "You are FinFit, a personal finance concierge. You help users manage active subscriptions, "
        "alert on upcoming bills, and generate custom saving strategies.\n"
        "You have access to two specialized sub-agents:\n"
        "1. subscription_agent: For subscription queries (list, analyze cost, flag high costs).\n"
        "2. savings_agent: For budget strategies, savings recommendations, and cost reduction tips.\n\n"
        "Determine the user's intent. Delegate to the appropriate specialist using their tool.\n"
        "You MUST respond using the OrchestratorOutput schema.\n"
        "If the user wants to cancel a subscription or apply a savings plan, set needs_confirmation=True, "
        "specify action_type ('cancel_subscription' or 'apply_savings'), and action_target (the subscription/strategy name)."
    ),
    tools=[AgentTool(subscription_agent), AgentTool(savings_agent)],
    output_schema=OrchestratorOutput,
)

# --- 6. Workflow Node Functions ---

@node
def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Scrubs PII, checks for prompt injection, and runs domain-specific safety checks."""
    user_text = ""
    if node_input and node_input.parts:
        user_text = "".join([p.text for p in node_input.parts if p.text])
        
    # 1. Prompt Injection Detection
    injection_keywords = ["ignore previous instructions", "override", "system prompt", "jailbreak", "ignore safety"]
    is_injection = any(kw in user_text.lower() for kw in injection_keywords)
    if is_injection:
        audit_log = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": "prompt_injection_attempt",
            "severity": "CRITICAL",
            "details": "User query triggered prompt injection keyword detection."
        }
        logs = ctx.state.get("security_audit_logs", [])
        logs.append(audit_log)
        return Event(
            output="Prompt injection attempt detected.",
            route="SECURITY_EVENT",
            state={"security_audit_logs": logs}
        )
        
    # 2. Domain-Specific Consent & Boundary Check
    # If the user tries to access or manage someone else's finances
    sharing_keywords = ["spouse", "wife", "husband", "partner", "friend", "son", "daughter", "parent"]
    is_external_request = any(kw in user_text.lower() for kw in sharing_keywords) and any(
        act in user_text.lower() for act in ["account", "card", "finance", "subscription", "spending", "money"]
    )
    if is_external_request:
        audit_log = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": "privacy_boundary_violation",
            "severity": "WARNING",
            "details": "User requested access to third-party accounts."
        }
        logs = ctx.state.get("security_audit_logs", [])
        logs.append(audit_log)
        return Event(
            output="Privacy Boundary: FinFit only supports managing your personal finance accounts. External account access is restricted.",
            route="SECURITY_EVENT",
            state={"security_audit_logs": logs}
        )
        
    # 3. PII Scrubbing (Email & Credit Card numbers)
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    card_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    
    scrubbed_text = re.sub(email_pattern, "[EMAIL_REDACTED]", user_text)
    scrubbed_text = re.sub(card_pattern, "[CARD_REDACTED]", scrubbed_text)
    
    pii_found = (scrubbed_text != user_text)
    
    # 4. Structured Audit Logging
    audit_log = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "query_scan",
        "severity": "WARNING" if pii_found else "INFO",
        "pii_redacted": pii_found
    }
    logs = ctx.state.get("security_audit_logs", [])
    logs.append(audit_log)
    
    return Event(
        output=scrubbed_text,
        route="safe",
        state={
            "scrubbed_query": scrubbed_text,
            "security_audit_logs": logs
        }
    )

@node
def security_violation_handler(ctx: Context, node_input: str) -> Event:
    """Handles security failures by informing the user and aborting flow."""
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=f"Blocked: {node_input}")]))
    yield Event(output=node_input)

@node(rerun_on_resume=True)
async def hitl_gate(ctx: Context, node_input: OrchestratorOutput) -> Event:
    """Verifies if the action needs human-in-the-loop confirmation before applying."""
    ctx.state["last_orchestrator_output"] = node_input.model_dump()
    
    if not node_input.needs_confirmation:
        # Yield the response for Web UI rendering
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=node_input.response)]))
        yield Event(output=node_input.response)
        return
        
    action_type = node_input.action_type
    action_target = node_input.action_target
    interrupt_id = f"confirm_{action_type}_{action_target}".replace(" ", "_").lower()
    
    if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
        # Prompt user for confirmation
        msg = f"Confirmation Required: Do you want to proceed with {action_type} for '{action_target}'? (Yes/No)"
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=msg
        )
        return
        
    user_response = ctx.resume_inputs[interrupt_id].strip().lower()
    if "yes" in user_response or user_response == "y":
        # Process action
        if action_type == "cancel_subscription":
            subscriptions = ctx.state.get("subscriptions", [])
            updated_subs = []
            cancelled_any = False
            for sub in subscriptions:
                sub_dict = sub if isinstance(sub, dict) else sub.model_dump()
                if sub_dict["name"].lower() == action_target.lower():
                    sub_dict["status"] = "cancelled"
                    cancelled_any = True
                updated_subs.append(sub_dict)
            
            ctx.state["subscriptions"] = updated_subs
            if cancelled_any:
                success_msg = f"Successfully cancelled subscription for '{action_target}'."
            else:
                success_msg = f"No active subscription found matching '{action_target}'."
        elif action_type == "apply_savings":
            success_msg = f"Applied savings strategy: '{action_target}' successfully."
        else:
            success_msg = f"Action {action_type} on '{action_target}' was executed successfully."
            
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=success_msg)]))
        yield Event(
            output=success_msg,
            state={"subscriptions": ctx.state.get("subscriptions")}
        )
    else:
        cancel_msg = f"Action '{action_type}' for '{action_target}' was cancelled."
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=cancel_msg)]))
        yield Event(output=cancel_msg)

# --- 7. Workflow Graph Definition ---
root_agent = Workflow(
    name="finfit_workflow",
    edges=[
        ('START', security_checkpoint),
        (security_checkpoint, {
            "safe": orchestrator_agent,
            "SECURITY_EVENT": security_violation_handler
        }),
        (orchestrator_agent, hitl_gate),
    ],
    state_schema=FinFitState,
)

app = App(
    root_agent=root_agent,
    name="app",
)
