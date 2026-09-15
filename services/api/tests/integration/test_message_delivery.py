"""Message delivery fan-out integration tests (FR-010): at-least-once, fail-closed."""

from __future__ import annotations

import pytest

from app.messaging.broker import MessageEnvelope, subject_for
from app.schemas.messages import MessageIn
from app.services import messages as message_service

pytestmark = pytest.mark.integration


def test_delivery_disabled_fails_closed_and_keeps_messages_pending(project: tuple) -> None:
    _app, client, _project_id, _tmp = project
    sent = client.post("/api/messages", json={"type": "request", "payload": {"hello": True}})
    assert sent.status_code == 201
    assert sent.json()["delivered_at"] is None

    response = client.post("/api/messages/deliver-pending")
    assert response.status_code == 503
    assert "NATS" in response.json()["detail"]

    conversation = sent.json()["conversation_id"]
    replayed = client.get(f"/api/conversations/{conversation}/messages").json()
    assert replayed and replayed[0]["delivered_at"] is None  # durable record untouched


def test_delivery_fan_out_marks_delivered_with_fake_broker(
    project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client, project_id, _tmp = project
    published: list[MessageEnvelope] = []

    class FakeBroker:
        async def publish(self, envelope: MessageEnvelope) -> None:
            published.append(envelope)

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.api.routes.orchestration.messages.build_broker", lambda _settings: FakeBroker()
    )

    recipient = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "receiver", "role": "implementer"}
    ).json()["id"]
    direct = client.post(
        "/api/messages",
        json={"type": "request", "recipient_agent_id": recipient, "payload": {}},
    ).json()
    client.post("/api/messages", json={"type": "broadcast", "payload": {}})

    result = client.post("/api/messages/deliver-pending")
    assert result.status_code == 200
    body = result.json()
    # The fan-out pass is global: every pending message gets delivered, ours included.
    assert body["delivered_count"] >= 2 and body["failed_count"] == 0
    assert {subject_for(env, "harness.msg") for env in published} >= {
        f"harness.msg.agent.{recipient}",
        "harness.msg.broadcast",
    }

    replayed = client.get(f"/api/conversations/{direct['conversation_id']}/messages").json()
    assert replayed[0]["delivered_at"] is not None

    again = client.post("/api/messages/deliver-pending").json()
    assert again["pending_count"] == 0 and again["delivered_count"] == 0


def test_message_service_envelope_roundtrip(project: tuple) -> None:
    app, _client, _project_id, _tmp = project
    with app.state.session_factory() as session:
        sent = message_service.send_message(session, MessageIn(type="question", payload={"q": 1}))
        rows = message_service.pending_messages(session, 10)
        envelope = message_service.envelope_from(rows[0])
        assert envelope.message_id == sent.id
        assert envelope.type == "question"
