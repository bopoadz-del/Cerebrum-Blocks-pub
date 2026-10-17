"""Wave 1.6 regression tests — primavera_parser CPM wiring.

Before the port, the block's "critical path" was a low-float filter over
P6's own exported floats and the Store's CPM engine (app/lib/pm_computations)
had zero callers. These lock that a known planted network computes the
real forward+backward pass: A(5d) -> B(3d) -> C(2d) is the critical chain
(10 days); D(1d) hangs off A with 4 days of float.
"""

import asyncio
import os
import tempfile

from app.blocks.primavera_parser import PrimaveraParserBlock


def _mini_xer(path: str) -> str:
    lines = [
        "ERMHDR\t7.0\t2024-01-01\tProject\tadmin\tA\tdb\tPM\tUSD",
        "%T\tCALENDAR",
        "%F\tclndr_id\tclndr_name\tday_hr_cnt",
        "%R\t1\tStandard\t8",
        "%T\tTASK",
        "%F\ttask_id\tproj_id\ttask_code\ttask_name\ttask_type\tstatus_code"
        "\ttarget_start_date\ttarget_end_date\ttarget_drtn_hr_cnt\tclndr_id",
        "%R\t1000\t1\tA\tMobilise\tTT_Task\tTK_NotStart\t2024-01-01\t2024-01-05\t40\t1",
        "%R\t1001\t1\tB\tExcavate\tTT_Task\tTK_NotStart\t2024-01-06\t2024-01-08\t24\t1",
        "%R\t1002\t1\tC\tBlind\tTT_Task\tTK_NotStart\t2024-01-09\t2024-01-10\t16\t1",
        "%R\t1003\t1\tD\tSurvey\tTT_Task\tTK_NotStart\t2024-01-06\t2024-01-06\t8\t1",
        "%T\tTASKPRED",
        "%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt",
        "%R\t1\t1001\t1000\tPR_FS\t0",
        "%R\t2\t1002\t1001\tPR_FS\t0",
        "%R\t3\t1003\t1000\tPR_FS\t0",
        "%E",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def test_real_cpm_replaces_low_float_filter():
    block = PrimaveraParserBlock()
    with tempfile.TemporaryDirectory() as td:
        xer = _mini_xer(os.path.join(td, "planted.xer"))
        out = asyncio.run(block.process({"file_path": xer}))

    assert out["status"] == "success", out.get("error")
    cpm = out["cpm"]
    assert cpm["total_duration_days"] == 10, cpm
    assert cpm["critical_path_activity_ids"] == ["A", "B", "C"], cpm
    assert cpm["per_activity_float"]["D"] == 4, cpm
    # The legacy low-float filter must NOT be called the critical path.
    assert "low_float_activities" in out
    assert out.get("_note") == "computed via real CPM forward+backward pass"
    assert out["calendars_parsed"]["1"]["hours_per_day"] == 8.0
