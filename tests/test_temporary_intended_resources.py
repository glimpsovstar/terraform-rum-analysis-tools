import json
from pathlib import Path

from temporary_intended_resources import extract_resources

FIX = Path(__file__).parent / "fixtures"


def test_finds_demo_named_instance(capsys):
    df = extract_resources(str(FIX / "sample_aws.tfstate"))
    assert df is not None
    assert (df["Resource Name"] == "web-demo").any()
    out = capsys.readouterr().out
    assert "Total Matching Instances Found: 1" in out


def test_azurerm_has_no_temp_names(capsys):
    df = extract_resources(str(FIX / "sample_azurerm.tfstate"))
    assert df is None
    assert "No matching resources found" in capsys.readouterr().out


def test_detailed_includes_attributes(capsys):
    df = extract_resources(str(FIX / "sample_aws.tfstate"), display_attributes=True)
    assert df is not None
    assert "Attributes" in df.columns
    assert "web-demo" in capsys.readouterr().out


def test_missing_file(capsys):
    extract_resources("/no/such/state.tfstate")
    assert "was not found" in capsys.readouterr().out
