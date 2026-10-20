from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from backend.config import settings
from backend.schemas.chat import MessageIn, ActionOut
from backend.nlu.prompts import build_system_prompt
from backend.nlu.tools import (
    CreateTaskArgs,
    CreateMeetingArgs,
    ListEventsArgs,
    SearchEventsArgs,
    AskClarificationArgs,
    UpdateEventArgs,
    CompleteEventArgs,
    DeleteEventArgs,
)
from backend.nlu.date_parser import RussianDateParser, ParsedDateTime
from backend.nlu.llm_client import LLMClient


@dataclass
class NLUResult:
    intent: str
    raw_text: str
    title: Optional[str] = None
    datetime: Optional[datetime] = None
    datetime_iso: Optional[str] = None
    has_explicit_time: bool = False
    period: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    record_type: Optional[str] = None
    search_query: Optional[str] = None
    target_query: Optional[str] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    missing_field: Optional[str] = None
    raw_arguments: dict[str, Any] = field(default_factory=dict)

    def to_action_out(self) -> ActionOut:
        status = "pending" if self.needs_clarification else "ok"
        return ActionOut(
            type=self.intent,
            status=status,
            record=None,
            records=None
        )


class NLUModule:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.llm_client = LLMClient(api_key=api_key, model=model)
        self.date_parser = RussianDateParser(default_tz=settings.tz)

    def parse(
        self,
        text: str,
        history: Optional[list[MessageIn]] = None,
        now: Optional[datetime] = None
    ) -> NLUResult:
        current_dt = now or datetime.now()
        system_content = build_system_prompt(current_dt, tz_name=settings.tz)

        messages = [{"role": "system", "content": system_content}]

        if history:
            for item in history[-6:]:
                messages.append({"role": item.role, "content": item.content})

        messages.append({"role": "user", "content": text})

        tool_name, args, _ = self.llm_client.call_tools(messages, now=current_dt)

        if tool_name == "create_task":
            validated_task = CreateTaskArgs(**args)
            parsed_dt = self.date_parser.parse(validated_task.datetime_str, base_dt=current_dt)
            return NLUResult(
                intent="create_task",
                raw_text=text,
                title=validated_task.title,
                datetime=parsed_dt.dt,
                datetime_iso=parsed_dt.iso,
                has_explicit_time=parsed_dt.has_explicit_time,
                period=parsed_dt.period,
                period_start=parsed_dt.period_start,
                period_end=parsed_dt.period_end,
                record_type=validated_task.record_type,
                raw_arguments=args
            )

        elif tool_name == "create_meeting":
            validated_meeting = CreateMeetingArgs(**args)
            parsed_dt = self.date_parser.parse(validated_meeting.datetime_str, base_dt=current_dt)

            if not parsed_dt.has_explicit_time:
                return NLUResult(
                    intent="ask_clarification",
                    raw_text=text,
                    title=validated_meeting.title,
                    needs_clarification=True,
                    clarification_question="На какое время поставить встречу?",
                    missing_field="time",
                    raw_arguments=args
                )

            return NLUResult(
                intent="create_meeting",
                raw_text=text,
                title=validated_meeting.title,
                datetime=parsed_dt.dt,
                datetime_iso=parsed_dt.iso,
                has_explicit_time=True,
                record_type="meeting",
                raw_arguments=args
            )

        elif tool_name == "list_events":
            validated_list = ListEventsArgs(**args)
            period_str = validated_list.period
            parsed_period = self.date_parser.parse(period_str, base_dt=current_dt)

            p_start = parsed_period.period_start
            p_end = parsed_period.period_end

            if validated_list.from_datetime:
                p_start = datetime.fromisoformat(validated_list.from_datetime)
            if validated_list.to_datetime:
                p_end = datetime.fromisoformat(validated_list.to_datetime)

            return NLUResult(
                intent="list_events",
                raw_text=text,
                period=period_str,
                period_start=p_start,
                period_end=p_end,
                record_type=validated_list.record_type,
                raw_arguments=args
            )

        elif tool_name == "search_events":
            validated_search = SearchEventsArgs(**args)
            return NLUResult(
                intent="search_events",
                raw_text=text,
                search_query=validated_search.query,
                record_type=validated_search.record_type,
                raw_arguments=args
            )

        elif tool_name == "ask_clarification":
            validated_clarification = AskClarificationArgs(**args)
            return NLUResult(
                intent="ask_clarification",
                raw_text=text,
                needs_clarification=True,
                clarification_question=validated_clarification.question,
                missing_field=validated_clarification.missing_field,
                raw_arguments=args
            )

        elif tool_name == "update_event":
            validated_update = UpdateEventArgs(**args)
            parsed_dt = self.date_parser.parse(validated_update.new_datetime_str, base_dt=current_dt)
            return NLUResult(
                intent="update_event",
                raw_text=text,
                target_query=validated_update.target_query,
                title=validated_update.new_title,
                datetime=parsed_dt.dt,
                datetime_iso=parsed_dt.iso,
                has_explicit_time=parsed_dt.has_explicit_time,
                raw_arguments=args
            )

        elif tool_name == "complete_event":
            validated_complete = CompleteEventArgs(**args)
            return NLUResult(
                intent="complete_event",
                raw_text=text,
                target_query=validated_complete.target_query,
                raw_arguments=args
            )

        elif tool_name == "delete_event":
            validated_delete = DeleteEventArgs(**args)
            return NLUResult(
                intent="delete_event",
                raw_text=text,
                target_query=validated_delete.target_query,
                raw_arguments=args
            )

        return NLUResult(
            intent="unknown",
            raw_text=text,
            raw_arguments=args
        )
