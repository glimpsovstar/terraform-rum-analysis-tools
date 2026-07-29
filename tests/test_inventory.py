import json
from pathlib import Path

from inventory import extract_inventory, normalize_provider

FIX = Path(__file__).parent / "fixtures"


def test_normalize_provider():
    assert normalize_provider('provider["registry.terraform.io/hashicorp/aws"]') == "hashicorp/aws"
    assert normalize_provider('provider["registry.terraform.io/hashicorp/azurerm"].prod') == "hashicorp/azurerm"
    assert normalize_provider("unknown") == "unknown"
    assert normalize_provider("") == "unknown"


def test_extract_counts_and_excludes_null_and_data():
    state = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))
    df = extract_inventory(state, workspace_name="ws1", organization="org")
    assert df["instance_count"].sum() == 2
    assert set(df["provider"]) == {"hashicorp/aws"}
    assert "null_resource" not in set(df["resource_type"])
    assert set(df["workspace_name"]) == {"ws1"}
    assert set(df["organization"]) == {"org"}


def test_extract_azurerm_alias_provider_and_excludes_terraform_data():
    state = json.loads((FIX / "sample_azurerm.tfstate").read_text(encoding="utf-8"))
    df = extract_inventory(state, workspace_name="ws2")
    assert df["instance_count"].sum() == 3
    assert set(df["provider"]) == {"hashicorp/azurerm"}
    assert "terraform_data" not in set(df["resource_type"])


def test_hide_and_only_hashi_filters():
    state = {
        "resources": [
            {
                "mode": "managed",
                "type": "tfe_workspace",
                "name": "ws",
                "provider": 'provider["registry.terraform.io/hashicorp/tfe"]',
                "instances": [{"attributes": {}}],
            },
            {
                "mode": "managed",
                "type": "aws_s3_bucket",
                "name": "b",
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [{"attributes": {}}],
            },
        ]
    }
    hidden = extract_inventory(state, hide_hashi=True)
    assert list(hidden["resource_type"]) == ["aws_s3_bucket"]
    only = extract_inventory(state, only_hashi=True)
    assert list(only["resource_type"]) == ["tfe_workspace"]
