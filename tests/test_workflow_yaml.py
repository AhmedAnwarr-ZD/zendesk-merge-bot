import os
import yaml


def test_workflow_yaml_exists_and_valid():
    path = os.path.join(
        os.getcwd(), ".github", "workflows", "zendesk_to_shopify.yml"
    )
    assert os.path.exists(path), "Workflow file not found"

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict)
    assert data.get("name")
    assert "jobs" in data
    assert "on" in data

    # Validate that the dispatch inputs include ticket_id
    wdispatch = data.get("on", {}).get("workflow_dispatch", {})
    inputs = wdispatch.get("inputs", {}) if isinstance(wdispatch, dict) else {}
    assert "ticket_id" in inputs