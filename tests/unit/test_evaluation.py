from app.evaluation import evaluate_sweep


def test_evaluation_marks_missing_packet_and_ground_truth_unmeasured(tmp_path) -> None:
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "count_gt.csv").write_text("unit,row,true_count\nA,1,\n", encoding="utf-8")

    output = evaluate_sweep(tmp_path / "sweep", gt, tmp_path / "results.md")

    text = output.read_text(encoding="utf-8")
    assert "Status: **BLOCKED**" in text
    assert "claim_packet.json is missing" in text
    assert "NOT MEASURED" in text
