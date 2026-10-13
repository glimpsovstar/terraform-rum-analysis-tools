import sys
from pathlib import Path

import pytest

from terraform_resource_extractor import (
    extract_resources,
    group_resources,
    load_state_file,
    main,
)

FIX = Path(__file__).parent / "fixtures"


def test_load_state_file():
    data = load_state_file(str(FIX / "sample_aws.tfstate"))
    assert "resources" in data


def test_load_state_file_missing():
    with pytest.raises(SystemExit) as exc:
        load_state_file("/no/such/file.tfstate")
    assert exc.value.code == 1


def test_load_state_file_invalid_json(tmp_path):
    bad = tmp_path / "bad.tfstate"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        load_state_file(str(bad))
    assert exc.value.code == 1


def test_cli_number(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["terraform_resource_extractor.py", "-f", str(FIX / "sample_aws.tfstate"), "-n"],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "Total number of resource instances: 2" in capsys.readouterr().out


def test_cli_aggregate(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["terraform_resource_extractor.py", "-f", str(FIX / "sample_aws.tfstate"), "-A"],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "Aggregate Information" in capsys.readouterr().out


def test_cli_default_table(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["terraform_resource_extractor.py", "-f", str(FIX / "sample_aws.tfstate")],
    )
    main()
    assert "Extracted Managed Resources" in capsys.readouterr().out


def test_cli_csv_output(monkeypatch, tmp_path, capsys):
    out = tmp_path / "rum.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "terraform_resource_extractor.py",
            "-f",
            str(FIX / "sample_aws.tfstate"),
            "-o",
            str(out),
        ],
    )
    main()
    written = out if out.exists() else Path(str(out) + ".csv")
    assert written.exists()
    assert "Results saved" in capsys.readouterr().out


def test_cli_debug_number(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["terraform_resource_extractor.py", "-f", str(FIX / "sample_aws.tfstate"), "-n", "-d"],
    )
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "DEBUG" in out
    assert "Total number of resource instances: 2" in out


def test_group_resources_returns_frame(capsys):
    import json

    state = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))
    df, _ = extract_resources(state)
    grouped = group_resources(df)
    assert grouped is not None
    assert "Grouped Resource Information" in capsys.readouterr().out


def test_empty_state_cli(monkeypatch, tmp_path, capsys):
    empty = tmp_path / "empty.tfstate"
    empty.write_text('{"resources": []}', encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["terraform_resource_extractor.py", "-f", str(empty)],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "No managed resources found" in capsys.readouterr().out
