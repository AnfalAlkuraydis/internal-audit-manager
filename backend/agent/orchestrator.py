"""One real tool-using agent, coordinated by LangGraph with SQLite checkpoints.

The graph does not prescribe a control/source sequence. Grok chooses tools;
Python validates operations and LangGraph handles pauses, replay and resumption.
"""
import asyncio
import json
import sqlite3
import threading
import time
from datetime import timedelta, date
from pathlib import Path
from typing import TypedDict
from uuid import uuid4, uuid5, NAMESPACE_URL
import sqlalchemy as sa
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command
from langsmith import tracing_context
from backend.agent.azure_grok import AzureGrok
from backend.agent.llm_interface import Message, InferenceResult, InferenceError, ToolDefinition
from backend.agent.tools.contracts import CONTRACTS, tool_definitions
from backend.agent.context import observe, update_work
from backend.agent.prompt import SYSTEM
from backend.auth import Principal
from backend.config import Settings
from backend.database import tables as t
from backend.database.schemas import Record, Identifier, Text, Engagement
from backend.database.repository import fingerprint, insert_unchanged
from backend.email.service import MailService
from backend.services.activity import utcnow, stamp, emit
from backend.services.errors import AuditError

class Scope(Record):
    """The model interprets dates/department, then backend validates the assignment."""
    department: Text
    period_start: date
    period_end: date

class AgentState(TypedDict, total=False):
    """Checkpoint only resumable context, references and bounded execution counters."""
    session_id: str
    assignment: str
    engagement_id: str
    messages: list[dict]
    pending_calls: list[dict]
    turn: int
    activation_steps: int
    nudges: int
    route: str
    status: str

class AgentRuntime:
    """Run one Manager per engagement with durable work, inference and action receipts."""

    def __init__(self, audit, checkpoint_path, *, llm=None, clock=utcnow,
                 inference_source="azure_grok", max_calls=100, activation_steps=6, mail=None):
        """Inject only test dependencies; production has LIVE Azure inference and simulated mail."""
        self.audit, self.engine, self.clock = audit, audit.engine, clock
        self.llm = llm
        self.inference_source = inference_source
        self.max_calls = max_calls
        self.activation_limit = activation_steps
        self.owner = str(uuid4())
        self.mail = mail or MailService(audit, clock=clock)
        self.lock = threading.RLock()
        path = Path(checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        graph = StateGraph(AgentState)
        graph.add_node("scope", self._scope)
        graph.add_node("reason", self._reason)
        graph.add_node("execute", self._execute)
        graph.add_node("wait", self._wait)
        graph.add_edge(START, "scope")
        graph.add_edge("scope", "reason")
        graph.add_conditional_edges("reason", lambda s: s["route"],
                                    {"execute": "execute", "wait": "wait", "reason": "reason", "end": END})
        graph.add_conditional_edges("execute", lambda s: s["route"],
                                    {"reason": "reason", "wait": "wait", "end": END})
        graph.add_edge("wait", "reason")
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def close(self):
        """Release the checkpoint connection after the owned worker has stopped."""
        self.connection.close()

    def start(self, assignment, dataset_id):
        """Persist an assignment immediately; the background worker interprets it with Grok."""
        if not isinstance(assignment, str) or not 1 <= len(assignment) <= 3000:
            raise AuditError("invalid_assignment", 422)
        id = str(uuid4())
        now = self.clock()
        with self.engine.begin() as c:
            self.audit._row(c, t.datasets, dataset_id)
            c.execute(t.agent_sessions.insert().values(
                id=id, engagement_id=None, dataset_id=dataset_id, assignment=assignment,
                status="queued", wake_version=1, handled_version=0, last_business_event="",
                lease_owner=None, lease_until=None, error_code=None, updated_at=stamp(now)))
            emit(c, "assignment:" + id, "Audit assignment received", "Running",
                 session_id=id, details={"assignment": assignment, "inference_source": self.inference_source}, now=now)
        return id

    def _heartbeat(self, session_id):
        """Renew the worker lease before a bounded external operation."""
        with self.engine.begin() as c:
            c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == session_id,
                t.agent_sessions.c.lease_owner == self.owner).values(
                lease_until=stamp(self.clock() + timedelta(seconds=120)), updated_at=stamp(self.clock())))

    def _infer(self, session_id, turn_key, messages, tools):
        """Cache completed inference before graph replay; never substitute mock inference on failure."""
        request = dict(messages=[m.model_dump(mode="json") for m in messages],
                       tools=[tool.model_dump() for tool in tools])
        digest = fingerprint(request)
        with self.engine.connect() as c:
            prior = c.execute(sa.select(t.agent_inferences).where(
                t.agent_inferences.c.session_id == session_id,
                t.agent_inferences.c.turn_key == turn_key)).mappings().first()
        if prior:
            # Replay the original decision; execution rechecks current permissions and scope.
            return InferenceResult.model_validate(prior["response"])
        self._heartbeat(session_id)
        if self.llm is None:
            self.llm = AzureGrok(Settings.from_env())
        for attempt in range(3):
            self._heartbeat(session_id)
            try:
                result = asyncio.run(self.llm.complete(messages, tools))
                break
            except InferenceError as error:
                with self.engine.begin() as c:
                    emit(c, f"inference-error:{session_id}:{turn_key}:{attempt}", "Model request failed: " + error.code,
                         "Failed", session_id=session_id, details={"retry": attempt, "code": error.code},
                         now=self.clock())
                if not error.retryable or attempt == 2:
                    raise
                time.sleep(error.retry_after_seconds or ((20 * (attempt + 1)) if error.code == "provider_http_429" else 2 ** attempt))
        with self.engine.begin() as c:
            c.execute(t.agent_inferences.insert().values(
                id=str(uuid4()), session_id=session_id, turn_key=turn_key, request_digest=digest,
                response=result.model_dump(mode="json"), offered_tools=[tool.name for tool in tools],
                created_at=stamp(self.clock())))
        return result

    def _scope(self, state):
        """Use actual inference to interpret a high-level assignment, then save stable engagement scope."""
        if state.get("engagement_id"):
            return {}
        with self.engine.connect() as c:
            session = self.audit._row(c, t.agent_sessions, state["session_id"])
            dataset = self.audit._row(c, t.datasets, session["dataset_id"])
        if session["engagement_id"]:
            return {"engagement_id": session["engagement_id"]}
        result = self._infer(state["session_id"], "scope", [
            Message(role="system", content=(
                "Interpret the audit assignment. Return ONLY JSON with department, period_start, period_end "
                "(ISO dates). Do not invent unspecified dates. Available department: " + dataset["department"])),
            Message(role="user", content=state["assignment"])], [])
        if result.message.tool_calls or not result.message.content:
            raise AuditError("assignment_scope_not_understood", 422)
        scope = Scope.model_validate(json.loads(result.message.content))
        id = str(uuid5(NAMESPACE_URL, state["session_id"] + ":engagement"))
        engagement = Engagement(id=id, dataset_id=dataset["id"], **scope.model_dump())
        if engagement.department != dataset["department"]:
            raise AuditError("assignment_department_not_available", 422)
        with self.engine.begin() as c:
            insert_unchanged(c, t.engagements, engagement.model_dump())
            c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == state["session_id"]).values(
                engagement_id=id, updated_at=stamp(self.clock())))
            emit(c, "scope:" + state["session_id"], "Audit scope interpreted and saved",
                 session_id=state["session_id"], engagement_id=id, record_type="engagement",
                 record_id=id, details=engagement.model_dump(mode="json"), now=self.clock())
        return {"engagement_id": id}

    def _tools(self, context):
        """Limit capabilities by current approvals, without selecting the model's next tool."""
        names = {"get_audit_requirements", "draft_audit_plan"}
        if context["plan"] and context["plan"]["status"] == "approved":
            names |= set(CONTRACTS) - {"manage_remediation"}
        if context["approved_findings"]:
            names.add("manage_remediation")
        definitions = []
        for definition in tool_definitions():
            if definition.name not in names:
                continue
            # Infrastructure IDs are server-owned; the model chooses business arguments only.
            schema = dict(definition.parameters)
            schema["properties"] = {k: v for k, v in schema["properties"].items()
                                    if k not in {"engagement_id", "operation_id"}}
            schema["required"] = [k for k in schema.get("required", [])
                                  if k not in {"engagement_id", "operation_id"}]
            definitions.append(ToolDefinition(name=definition.name, description=definition.description,
                                              parameters=schema))
        return definitions

    def _recent(self, messages):
        """Bound context size while retaining complete assistant/tool-result groups."""
        recent = messages[-8:]
        while recent and recent[0]["role"] == "tool":
            recent = recent[1:]
        return [Message.model_validate(m) for m in recent]

    def _reason(self, state):
        """Ask Grok to choose tools from the current factual state, or stop at a real wait."""
        context = observe(self.audit, state["engagement_id"], self.clock())
        if context["pending_plan"]:
            return {"route": "wait", "status": "waiting"}
        with self.engine.connect() as c:
            calls = c.scalar(sa.select(sa.func.count()).select_from(t.agent_calls).where(
                t.agent_calls.c.session_id == state["session_id"]))
        if calls >= self.max_calls:
            raise AuditError("agent_action_budget_exhausted")
        messages = [Message(role="system", content=SYSTEM),
                    Message(role="system", content=json.dumps(context, separators=(",", ":"))),
                    Message(role="user", content=state["assignment"])] + self._recent(state.get("messages", []))
        result = self._infer(state["session_id"], "turn:" + str(state.get("turn", 0)),
                             messages, self._tools(context))
        history = state.get("messages", []) + [result.message.model_dump(mode="json")]
        changes = dict(messages=history, turn=state.get("turn", 0) + 1,
                       activation_steps=state.get("activation_steps", 0) + 1)
        if result.message.tool_calls:
            if len(result.message.tool_calls) > 8:
                raise AuditError("too_many_parallel_tool_calls")
            return {**changes, "pending_calls": [call.model_dump(mode="json") for call in result.message.tool_calls],
                    "nudges": 0, "route": "execute", "status": "running"}
        if context["needs"]:
            if state.get("nudges", 0) >= 2:
                raise AuditError("agent_stopped_with_pending_work")
            history.append(Message(role="user", content="Actual backend still has actionable work: "
                                   + json.dumps(context["needs"]) + ". Continue independently.").model_dump(mode="json"))
            return {**changes, "messages": history, "nudges": state.get("nudges", 0) + 1, "route": "reason"}
        if context["waiting"]:
            return {**changes, "route": "wait", "status": "waiting"}
        with self.engine.begin() as c:
            emit(c, "complete:" + state["session_id"], "Audit execution and approved follow-up completed",
                 session_id=state["session_id"], engagement_id=state["engagement_id"],
                 details={"summary": result.message.content or ""}, now=self.clock())
        return {**changes, "route": "end", "status": "completed"}

    def _execute(self, state):
        """Execute model-selected calls with stable retry keys and real saved outcomes."""
        history = list(state["messages"])
        for call in state["pending_calls"]:
            self._heartbeat(state["session_id"])
            with self.engine.connect() as c:
                prior = c.execute(sa.select(t.agent_calls).where(
                    t.agent_calls.c.session_id == state["session_id"],
                    t.agent_calls.c.call_id == call["id"])).mappings().first()
            if prior:
                if prior["tool"] != call["name"] or prior["arguments"] != call["arguments"]:
                    raise AuditError("model_call_id_reused")
                outcome = prior["result"]
            else:
                with self.engine.begin() as c:
                    emit(c, state["session_id"] + ":" + call["id"] + ":running",
                         "Running " + call["name"], "Running", session_id=state["session_id"],
                         engagement_id=state["engagement_id"], now=self.clock())
                started = time.perf_counter()
                success, schema_valid = False, False
                try:
                    context = observe(self.audit, state["engagement_id"], self.clock())
                    if call["name"] not in {d.name for d in self._tools(context)}:
                        raise AuditError("tool_not_available_at_this_stage", 403)
                    if {"engagement_id", "operation_id"} & set(call["arguments"]):
                        raise AuditError("model_supplied_server_owned_id", 403)
                    arguments = {**call["arguments"], "engagement_id": state["engagement_id"],
                        "operation_id": str(uuid5(NAMESPACE_URL, state["session_id"] + ":" + call["id"]))}
                    CONTRACTS[call["name"]][0].model_validate(arguments)
                    schema_valid = True
                    result = self.audit.invoke(call["name"], arguments, Principal("audit-agent", "agent"))
                    if call["name"] == "run_control_test":
                        update_work(self.audit, state["engagement_id"], result["run_id"], self.clock())
                    outcome, success = {"ok": True, "result": result}, True
                except (AuditError, ValueError, ValidationError) as error:
                    outcome = {"ok": False, "error": getattr(error, "code", "invalid_tool_arguments")}
                with self.engine.begin() as c:
                    c.execute(t.agent_calls.insert().values(id=str(uuid4()), session_id=state["session_id"],
                        call_id=call["id"], tool=call["name"], arguments=call["arguments"],
                        result=outcome, success=success, schema_valid=schema_valid,
                        duration_ms=(time.perf_counter() - started) * 1000, created_at=stamp(self.clock())))
                    result = outcome.get("result", {})
                    reference = next((result[k] for k in (
                        "proposal_id", "request_id", "run_id", "evidence_snapshot_id", "population_snapshot_id")
                        if k in result), None)
                    label = call["name"] + (" completed" if success else " failed: " + outcome["error"])
                    if "counts" in result:
                        label = "Control testing saved: " + ", ".join(f"{n} {s}" for s, n in result["counts"].items() if n)
                    status = "Completed" if success else "Failed"
                    if result.get("status") == "pending":
                        status = "Waiting for Approval"
                    emit(c, state["session_id"] + ":" + call["id"] + ":done", label, status,
                        session_id=state["session_id"], engagement_id=state["engagement_id"],
                        record_type=call["name"], record_id=reference, details=outcome, now=self.clock())
            history.append(Message(role="tool", tool_call_id=call["id"],
                                   content=json.dumps(outcome, separators=(",", ":"))).model_dump(mode="json"))
        context = observe(self.audit, state["engagement_id"], self.clock())
        route = "wait" if context["pending_plan"] else (
            "end" if state["activation_steps"] >= self.activation_limit else "reason")
        return {"messages": history, "pending_calls": [], "route": route,
                "status": "waiting" if route == "wait" else "queued" if route == "end" else "running"}

    def _wait(self, state):
        """Persist a real external-event wait; resumption re-enters reasoning, never approval."""
        interrupt({"engagement_id": state["engagement_id"], "reason": "External evidence or human decision required"})
        return {"messages": state["messages"] + [Message(role="user", content=(
            "A persisted backend event arrived. Re-read current observations and resume affected work; "
            "no new auditor instruction is required.")).model_dump(mode="json")],
            "status": "running", "activation_steps": 0, "nudges": 0}

    def _sync_reviews(self, c, session):
        """Notice human decisions even when they came through direct service calls before restart."""
        if not session["engagement_id"]:
            return
        events = c.execute(sa.select(t.audit_events).where(
            t.audit_events.c.engagement_id == session["engagement_id"],
            t.audit_events.c.created_at > session["last_business_event"],
            sa.or_(t.audit_events.c.event.like("review_%"),
                   t.audit_events.c.event == "department_action_plan_recorded"))
            .order_by(t.audit_events.c.created_at)).mappings().all()
        if events:
            c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == session["id"]).values(
                wake_version=t.agent_sessions.c.wake_version + 1,
                last_business_event=events[-1]["created_at"]))
            for event in events:
                emit(c, "review-event:" + event["id"], event["event"].replace("_", " "),
                     "Resumed", session_id=session["id"], engagement_id=session["engagement_id"],
                     record_type="review", record_id=event["record_id"], now=self.clock())

    def tick(self):
        """Process mail automatically and advance one runnable graph with crash-recovery leases."""
        with self.lock:
            self.mail.tick()
            now = self.clock()
            with self.engine.begin() as c:
                c.exec_driver_sql("BEGIN IMMEDIATE")
                for session in c.execute(sa.select(t.agent_sessions).where(
                        t.agent_sessions.c.status != "paused")).mappings().all():
                    self._sync_reviews(c, session)
                candidates = c.execute(sa.select(t.agent_sessions).where(
                    # Paused audits stay dormant even when new business events arrive.
                    t.agent_sessions.c.status != "paused",
                    sa.or_(t.agent_sessions.c.status == "queued",
                        sa.and_(t.agent_sessions.c.status == "running", t.agent_sessions.c.lease_until < stamp(now)),
                        t.agent_sessions.c.wake_version > t.agent_sessions.c.handled_version),
                    sa.or_(t.agent_sessions.c.lease_until.is_(None), t.agent_sessions.c.lease_until < stamp(now)))
                    .order_by(t.agent_sessions.c.updated_at)).mappings().first()
                if not candidates:
                    return None
                session = dict(candidates)
                c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == session["id"]).values(
                    status="running", lease_owner=self.owner, lease_until=stamp(now + timedelta(seconds=120)),
                    updated_at=stamp(now)))
            config = {"configurable": {"thread_id": session["id"]}, "recursion_limit": 120}
            try:
                snapshot = self.graph.get_state(config)
                if snapshot.next:
                    argument = Command(resume={"event": "backend_change"}) if any(
                        task.interrupts for task in snapshot.tasks) else None
                else:
                    argument = dict(session_id=session["id"], assignment=session["assignment"],
                        activation_steps=0, nudges=0, status="running")
                # No external tracing service is part of this local architecture.
                with tracing_context(enabled=False):
                    output = self.graph.invoke(argument, config)
                after = self.graph.get_state(config)
                status = "waiting" if any(task.interrupts for task in after.tasks) else output.get("status", "queued")
                error = None
            except Exception as failure:
                status, error = "attention_required", getattr(failure, "code", type(failure).__name__)
                with self.engine.begin() as c:
                    emit(c, str(uuid4()), "Agent needs attention: " + error, "Failed",
                         session_id=session["id"], engagement_id=session["engagement_id"],
                         details={"error_code": error}, now=self.clock())
            with self.engine.begin() as c:
                c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == session["id"],
                    t.agent_sessions.c.lease_owner == self.owner).values(
                    status=status, error_code=error, handled_version=session["wake_version"],
                    lease_owner=None, lease_until=None, updated_at=stamp(self.clock())))
            self.mail.tick()
            return session["id"]
