import db
import evaluate
from disputes import adversarial
from disputes import metrics as dispute_metrics


def test_every_case_type_has_an_expectation_and_four_cases(fresh_db):
    for case_type in adversarial.CASE_TYPES:
        assert case_type["truth"] in ("escalate", "contest")
        assert case_type["expected_agent"] in ("auto_submit", "escalate")
        assert case_type["why"] and case_type["kind"] in ("probe", "control")
        n = db.one("SELECT COUNT(*) AS n FROM disputes WHERE scenario=?",
                   (f"adv:{case_type['name']}",))["n"]
        assert n == adversarial.CASES_PER_TYPE


def test_there_are_probes_and_controls(fresh_db):
    kinds = [c["kind"] for c in adversarial.CASE_TYPES]
    assert kinds.count("probe") >= 5 and kinds.count("control") >= 2


def test_report_is_per_type_with_no_blended_rate(fresh_db):
    evaluate.run_all()
    report = dispute_metrics.adversarial_report()
    assert [r["type"] for r in report] == [c["name"] for c in adversarial.CASE_TYPES]
    for row in report:
        assert row["cases"] == adversarial.CASES_PER_TYPE
        assert row["auto_submitted"] + row["escalated"] == row["cases"]
        assert not {"rate", "overall", "total", "blended"} & set(row)
    assert isinstance(report, list)


def test_controls_are_caught_by_the_current_rules(fresh_db):
    """If a control slipped through, the probes would not be a fair test."""
    evaluate.run_all()
    for row in dispute_metrics.adversarial_report():
        if row["kind"] == "control":
            assert row["wrong_auto_submissions"] == 0, row["type"]


def test_results_that_differ_from_the_written_prediction_are_visible(fresh_db):
    evaluate.run_all()
    for row in dispute_metrics.adversarial_report():
        assert 0 <= row["matched_expectation"] <= row["cases"]


def test_adversarial_cases_stay_out_of_the_main_metrics(fresh_db):
    evaluate.run_all()
    main = db.one("SELECT COUNT(*) AS n FROM disputes WHERE suite='main'")["n"]
    assert dispute_metrics.compute_metrics()["processed"] == main


def test_each_gap_is_really_built_into_the_records(fresh_db):
    ids = {name: db.one("SELECT dispute_id FROM disputes WHERE scenario=? ORDER BY dispute_id",
                        (f"adv:{name}",))["dispute_id"] for name in adversarial.by_name()}
    order = lambda d: db.one("SELECT o.* FROM orders o JOIN disputes x ON x.notice_text LIKE '%' || o.order_id || '%' "
                             "WHERE x.dispute_id=? AND o.order_id NOT LIKE '%-%-%'", (d,))
    n = ids["wrong_address_proof"].split("-")[-1]
    ship = db.one("SELECT ship_to FROM orders WHERE order_id=?", (f"ORD-{10000 + int(n)}",))["ship_to"]
    got = db.one("SELECT delivered_to FROM deliveries WHERE delivery_id=?", (f"DLV-{70000 + int(n)}",))["delivered_to"]
    assert ship != got
    n = ids["partial_refund_before_chargeback"].split("-")[-1]
    assert db.one("SELECT COUNT(*) AS c FROM refunds WHERE txn_id=?", (f"TXN-{50000 + int(n)}",))["c"] == 1
    n = ids["double_charge_same_order"].split("-")[-1]
    assert db.one("SELECT COUNT(*) AS c FROM payments WHERE order_id=?", (f"ORD-{10000 + int(n)}",))["c"] == 2
    n = ids["reused_proof_ref"].split("-")[-1]
    ref = db.one("SELECT proof_ref FROM deliveries WHERE delivery_id=?", (f"DLV-{70000 + int(n)}",))["proof_ref"]
    assert db.one("SELECT COUNT(*) AS c FROM deliveries WHERE proof_ref=?", (ref,))["c"] == 2
