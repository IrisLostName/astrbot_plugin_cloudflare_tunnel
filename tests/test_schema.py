import json
from pathlib import Path


def test_health_check_schema_has_addable_template():
    schema = json.loads((Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(encoding="utf-8"))
    template = schema["extra_health_checks"]["templates"]["check"]
    assert template["display_item"] == "name"
    assert set(template["items"]) == {"name", "url", "expected_statuses", "enabled"}
    assert template["items"]["expected_statuses"]["default"] == [200, 302, 401, 403]
