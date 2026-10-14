from pathlib import Path

from extract_resource_type_stats import extract_resource_instances

FIX = Path(__file__).parent / "fixtures"


def test_extracts_matching_resource_type(capsys):
    df = extract_resource_instances(str(FIX / "sample_aws.tfstate"), "aws_instance")
    assert df is not None
    assert len(df) == 2
    out = capsys.readouterr().out
    assert "Total `aws_instance` Instances Found: 2" in out


def test_missing_type_returns_none(capsys):
    df = extract_resource_instances(str(FIX / "sample_aws.tfstate"), "aws_vpc")
    assert df is None
    assert "No `aws_vpc` instances found" in capsys.readouterr().out


def test_detailed_output_includes_attributes(capsys):
    df = extract_resource_instances(
        str(FIX / "sample_aws.tfstate"), "aws_instance", detailed_output=True
    )
    assert df is not None
    out = capsys.readouterr().out
    assert "Unique aws_instance Instances" in out
    assert "web-demo" in out


def test_missing_file(capsys):
    extract_resource_instances("/no/such/state.tfstate", "aws_instance")
    assert "was not found" in capsys.readouterr().out


def test_invalid_json(tmp_path, capsys):
    bad = tmp_path / "bad.tfstate"
    bad.write_text("{not-json", encoding="utf-8")
    extract_resource_instances(str(bad), "aws_instance")
    assert "not a valid JSON file" in capsys.readouterr().out
