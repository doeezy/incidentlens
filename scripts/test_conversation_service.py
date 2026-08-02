from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.incident_agent import ConversationHistoryMessage
from app.config import Settings
from app.schemas.incident_search import IncidentAgentResponse
from app.services.conversations import ConversationService


class _FakeTrace:
    def __init__(self, marker: str) -> None:
        self.marker = marker

    def model_dump(self, mode: str = "python"):
        return {"trace_version": "v1", "marker": self.marker}


class _FakeAgent:
    def __init__(self) -> None:
        self.calls = []
        self.last_trace = _FakeTrace("initial")

    def answer(self, **kwargs):
        self.calls.append(kwargs)
        self.last_trace = _FakeTrace(kwargs["question"])
        return IncidentAgentResponse(
            question=kwargs["question"],
            project_name=kwargs["project_name"],
            intent="SUMMARY",
            retrieval_required=True,
            rewritten_query=kwargs["question"],
            analysis_reason="test",
            answer=f"answer: {kwargs['question']}",
            search_results=[],
        )


class _FakeRepository:
    def __init__(self) -> None:
        self.conversation = SimpleNamespace(
            id=uuid.uuid4(),
            project_name="data-portal",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.messages = []
        self.commits = 0
        self.rollbacks = 0

    def create_conversation(self, project_name: str):
        self.conversation.project_name = project_name
        return self.conversation

    def get_conversation(self, conversation_id: uuid.UUID):
        return self.conversation if conversation_id == self.conversation.id else None

    def list_messages(self, conversation_id: uuid.UUID):
        return sorted(self.messages, key=lambda message: message.created_at)

    def list_recent_messages(self, *, conversation_id: uuid.UUID, limit: int):
        ordered = self.list_messages(conversation_id)
        return ordered[-limit:]

    def add_message(self, *, conversation, role, content, trace_json=None):
        message = SimpleNamespace(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role=role,
            content=content,
            trace_json=trace_json,
            created_at=datetime.now(timezone.utc) + timedelta(microseconds=len(self.messages)),
        )
        self.messages.append(message)
        return message

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ConversationServiceTest(unittest.TestCase):
    def service(self, *, history_limit: int = 5):
        repo = _FakeRepository()
        agent = _FakeAgent()
        service = ConversationService(
            settings=Settings(openai_api_key=None, conversation_history_limit=history_limit),
            repository=repo,  # type: ignore[arg-type]
            agent=agent,  # type: ignore[arg-type]
        )
        return service, repo, agent

    def test_create_answer_and_trace_message_saved(self) -> None:
        service, repo, agent = self.service()

        created = service.create_conversation("data-portal")
        response = service.answer(
            conversation_id=created.conversation_id,
            question="로그인 장애 원인 알려줘",
            top_k=3,
            request_id="req-1",
        )

        self.assertEqual(response.answer, "answer: 로그인 장애 원인 알려줘")
        self.assertEqual([message.role for message in repo.messages], ["USER", "ASSISTANT"])
        self.assertIsNone(repo.messages[0].trace_json)
        self.assertEqual(repo.messages[1].trace_json["marker"], "로그인 장애 원인 알려줘")
        self.assertEqual(agent.calls[0]["history_messages"], [])

    def test_second_question_receives_recent_history(self) -> None:
        service, repo, agent = self.service()
        conversation_id = repo.conversation.id

        service.answer(conversation_id=conversation_id, question="로그인 장애 원인이 뭐야?", top_k=3)
        service.answer(conversation_id=conversation_id, question="어떻게 해결했어?", top_k=3)

        history = agent.calls[1]["history_messages"]
        self.assertEqual(
            [(message.role, message.content) for message in history],
            [
                ("USER", "로그인 장애 원인이 뭐야?"),
                ("ASSISTANT", "answer: 로그인 장애 원인이 뭐야?"),
            ],
        )

    def test_get_conversation_returns_messages_in_created_order(self) -> None:
        service, repo, _agent = self.service()
        service.answer(
            conversation_id=repo.conversation.id,
            question="첫 질문",
            top_k=3,
        )
        service.answer(
            conversation_id=repo.conversation.id,
            question="두번째 질문",
            top_k=3,
        )

        read = service.get_conversation(repo.conversation.id)

        self.assertEqual(
            [message.content for message in read.messages],
            ["첫 질문", "answer: 첫 질문", "두번째 질문", "answer: 두번째 질문"],
        )

    def test_history_limit_is_applied(self) -> None:
        service, repo, agent = self.service(history_limit=5)
        base_time = datetime.now(timezone.utc)
        for index in range(10):
            repo.messages.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    conversation_id=repo.conversation.id,
                    role="USER" if index % 2 == 0 else "ASSISTANT",
                    content=f"message-{index}",
                    trace_json=None,
                    created_at=base_time + timedelta(seconds=index),
                )
            )

        service.answer(
            conversation_id=repo.conversation.id,
            question="어떻게 해결했어?",
            top_k=3,
        )

        history = agent.calls[0]["history_messages"]
        self.assertEqual(len(history), 5)
        self.assertEqual([message.content for message in history], [f"message-{index}" for index in range(5, 10)])
        self.assertTrue(all(isinstance(message, ConversationHistoryMessage) for message in history))


if __name__ == "__main__":
    unittest.main()
