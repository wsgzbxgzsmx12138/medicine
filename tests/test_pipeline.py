from pathlib import Path

from core.pipeline import run_pipeline


def test_pipeline_normal():
    root = Path(__file__).resolve().parents[1]
    upload = root / "data" / "upload" / "normal"
    output = root / "data" / "output" / "test_run"
    result = run_pipeline(upload, output)
    assert len(result.file_list) == 10
    assert result.catalog_df is not None
    assert Path(result.report_path).exists()
    assert len(result.completeness_issues) >= 1
