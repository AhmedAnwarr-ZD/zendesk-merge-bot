import builtins
import types
import json
import os
import importlib
import requests
import script

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Provide required environment variables for each test and ensure isolation
    monkeypatch.setenv("EMAIL", "agent@example.com")
    monkeypatch.setenv("API_TOKEN", "zdtok_123")
    monkeypatch.setenv("SUBDOMAIN", "acme")
    monkeypatch.setenv("SHOPIFY_TOKEN", "shop_tok_456")
    monkeypatch.setenv("SHOPIFY_DOMAIN", "myshopdomain")
    yield


class DummyResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_get_order_id_from_ticket_extracts_number():
    ticket = {"subject": "Customer inquiry (Order #12345)"}
    assert script.get_order_id_from_ticket(ticket) == "12345"


def test_get_order_id_from_ticket_returns_none_when_absent():
    ticket = {"subject": "General question about product"}
    assert script.get_order_id_from_ticket(ticket) is None


def test_get_order_id_handles_missing_subject():
    ticket = {"description": "No subject present"}
    assert script.get_order_id_from_ticket(ticket) is None


def test_get_zendesk_ticket_success(monkeypatch):
    captured = {}

    def fake_get(url, auth):
        captured["url"] = url
        captured["auth"] = auth
        return DummyResponse(
            200,
            payload={
                "ticket": {
                    "id": 77,
                    "subject": "Order #88888 refund",
                    "description": "Please refund",
                }
            },
        )

    monkeypatch.setattr(script.requests, "get", fake_get)

    ticket = script.get_zendesk_ticket(77)

    assert ticket["id"] == 77
    assert captured["url"].endswith("/tickets/77.json")
    assert captured["url"].startswith("https://acme.zendesk.com/api/v2/")
    assert captured["auth"] == ("agent@example.com/token", "zdtok_123")


def test_append_order_note_success(monkeypatch):
    captured = {}

    def fake_put(url, headers, json):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return DummyResponse(200, payload={"order": {"id": json["order"]["id"]}})

    monkeypatch.setattr(script.requests, "put", fake_put)

    response = script.append_order_note("12345", "Hello note")

    assert captured["url"].startswith(
        "https://myshopdomain.myshopify.com/admin/api/2024-01/orders/12345.json"
    )
    assert captured["headers"]["X-Shopify-Access-Token"] == "shop_tok_456"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert isinstance(captured["json"]["order"]["id"], int)
    assert captured["json"]["order"]["note"] == "Hello note"
    assert response["order"]["id"] == 12345


def test_sync_note_no_order_id(monkeypatch, capsys):
    # Stub get_zendesk_ticket to return a ticket without order number in subject
    monkeypatch.setattr(
        script, "get_zendesk_ticket", lambda tid: {"id": tid, "subject": "Hello"}
    )

    script.sync_note(999)

    out = capsys.readouterr().out
    assert "No Shopify order ID found in ticket 999" in out


def test_sync_note_success(monkeypatch, capsys):
    # Provide a ticket containing an order number and description
    monkeypatch.setattr(
        script,
        "get_zendesk_ticket",
        lambda tid: {
            "id": tid,
            "subject": "Need update for order #54321",
            "description": "Please add a note",
        },
    )

    calls = {}

    def fake_append(order_id, note_text):
        calls["order_id"] = order_id
        calls["note_text"] = note_text
        return {"ok": True}

    monkeypatch.setattr(script, "append_order_note", fake_append)

    script.sync_note(42)

    out = capsys.readouterr().out
    assert calls["order_id"] == "54321"
    assert calls["note_text"].startswith("Zendesk Ticket #42:")
    assert "Synced ticket #42 to Shopify order #54321" in out


def test_missing_env_vars_raise_runtimeerror(monkeypatch):
    # Unset required env to trigger validation
    for key in [
        "EMAIL",
        "API_TOKEN",
        "SUBDOMAIN",
        "SHOPIFY_TOKEN",
        "SHOPIFY_DOMAIN",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError) as exc:
        script._get_required_config()

    assert "Missing required environment variables" in str(exc.value)