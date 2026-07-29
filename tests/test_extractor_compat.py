import json
from pathlib import Path

from inventory import extract_inventory
from terraform_resource_extractor import extract_resources

FIX = Path(__file__).parent / "fixtures"


def test_extractor_matches_inventory_totals_aws():
    state = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))
    df, _hashi = extract_resources(state)
    inv = extract_inventory(state)
    assert len(df) == int(inv["instance_count"].sum()) == 2
    assert set(df["Resource Type"]) == set(inv["resource_type"]) == {"aws_instance"}


def test_extractor_matches_inventory_totals_azurerm():
    state = json.loads((FIX / "sample_azurerm.tfstate").read_text(encoding="utf-8"))
    df, _hashi = extract_resources(state)
    inv = extract_inventory(state)
    assert len(df) == int(inv["instance_count"].sum()) == 3


def test_hide_hashi_aligned():
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
    df, hashi = extract_resources(state, exclude_tfe_vault=True)
    inv = extract_inventory(state, hide_hashi=True)
    assert len(df) == len(inv) == 1
    assert hashi == 1
