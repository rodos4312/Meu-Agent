"""Deterministic EA arithmetic contracts; no broker or model dependencies."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "optional-skills/research/mt5-market-data/scripts/ea_metrics.py"
BASE = 1793664000000
START = "2026-11-03T00:00:00Z"
END = "2026-11-04T00:00:00Z"


@pytest.fixture
def metrics():
    spec = importlib.util.spec_from_file_location("meu_ea_metrics_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(ticket, pid, entry, *, volume="0.03", profit="0", commission="-0.09", fee="0", stamp=None):
    return {"ticket": ticket, "position_id": pid, "magic": 151515, "symbol": "XAUUSD",
            "entry": entry, "entry_code": {"in": 0, "out": 1, "inout": 2, "unknown": 99}[entry],
            "type": "buy" if entry == "in" else "sell", "reason": 3,
            "volume": volume, "profit": profit, "swap": "0", "commission": commission,
            "fee": fee, "time_msc": stamp if stamp is not None else BASE + ticket * 1000}


def run(metrics, rows, positions=None):
    return metrics.summarize_ea(rows, positions or [], from_ts=START, to_ts=END,
                                magic=151515, positions_at_utc=END)


def test_reconciles_full_positions_carry_exit_and_open_entry(metrics):
    rows = [row(1, 10, "in"), row(2, 10, "out", profit="10.18"),
            row(3, 20, "in"), row(4, 20, "out", profit="-5.82"),
            row(5, 30, "out", profit="2.09"), row(6, 40, "in")]
    positions = [{"identifier": 40, "magic": 151515, "symbol": "XAUUSD", "type": "buy",
                  "volume": "0.03", "profit": "99.1", "swap": "-0.1"}]
    result = run(metrics, rows, positions)
    assert result["validation"]["status"] == "passed"
    assert result["counts"]["trade_deals"] == 6
    assert result["counts"]["entries"] == 3 and result["counts"]["exits"] == 3
    assert result["counts"]["complete_trades"] == 2
    assert result["complete_trades"]["wins"] == result["complete_trades"]["losses"] == 1
    assert result["complete_trades"]["net"] == "4"
    assert result["net_by_status"]["exit_only"] == "2"
    assert result["counts"]["positions_by_status"]["exit_only"] == 1
    assert next(g for g in result["groups"] if g["status"] == "exit_only")["direction"] == "buy"
    assert result["net_by_status"]["entry_only"] == "-0.09"
    assert result["history_totals"]["net"] == "5.91"
    assert result["open_positions"]["floating_excluding_fees"] == "99"
    assert result["reconciliation"]["difference"] == "0"
    assert result["exit_reasons"]["expert"] == 2


def test_partial_exits_count_one_completed_position(metrics):
    rows = [row(1, 10, "in", volume="0.03"), row(2, 10, "out", volume="0.01", profit="1"),
            row(3, 10, "out", volume="0.02", profit="2")]
    result = run(metrics, rows)
    assert result["counts"]["complete_trades"] == 1 and result["counts"]["exits"] == 2
    assert result["complete_trades"]["net"] == "2.73"
    assert result["counts"]["positions_with_partial_exits"] == 1
    assert result["overlap"]["available"] is False


def test_remaining_volume_never_becomes_a_completed_trade(metrics):
    result = run(metrics, [row(1, 10, "in"), row(2, 10, "out", volume="0.01")])
    assert result["counts"]["complete_trades"] == 0
    assert result["groups"][0]["status"] == "partial_or_incomplete"
    assert result["groups"][0]["remaining_volume"] == "0.02"


def test_duplicate_identical_deal_is_counted_once(metrics):
    one = row(1, 10, "in")
    result = run(metrics, [one, dict(one)])
    assert result["counts"]["input_records"] == 2
    assert result["counts"]["trade_deals"] == 1
    assert result["validation"]["duplicate_records_ignored"] == 1
    assert result["history_totals"]["net"] == "-0.09"


def test_conflicting_duplicate_refuses_verified_summary(metrics):
    with pytest.raises(ValueError, match="duplicate"):
        run(metrics, [row(1, 10, "in"), row(1, 10, "in", profit="999")])


@pytest.mark.parametrize("field,value", [("profit", "NaN"), ("swap", "Infinity"),
                                         ("fee", "not-money"), ("volume", "-0.03"), ("profit", 0.1)])
def test_invalid_numeric_input_refuses_verified_summary(metrics, field, value):
    item = row(1, 10, "in"); item[field] = value
    with pytest.raises(ValueError):
        run(metrics, [item])


def test_missing_charge_is_not_silently_assumed_zero(metrics):
    item = row(1, 10, "in"); del item["fee"]
    with pytest.raises(ValueError, match="fee"):
        run(metrics, [item])


def test_foreign_magic_and_outside_window_are_rejected(metrics):
    for changes in ({"magic": 999}, {"time_msc": BASE - 1}):
        item = row(1, 10, "in"); item.update(changes)
        with pytest.raises(ValueError):
            run(metrics, [item])


def test_reversal_and_unknown_entries_are_not_completed_trades(metrics):
    for entry in ("inout", "unknown"):
        result = run(metrics, [row(1, 10, entry)])
        assert result["counts"]["complete_trades"] == 0
        assert result["groups"][0]["status"] == "ambiguous"
        assert result["reconciliation"]["difference"] == "0"


def test_empty_results_are_verified_without_invented_win_rate(metrics):
    result = run(metrics, [])
    assert result["history_totals"]["net"] == "0"
    assert result["complete_trades"]["win_rate_percent"] is None
    assert result["complete_trades"]["profit_factor"] is None


def test_reason_codes_and_positive_stop_loss_are_not_reinterpreted(metrics):
    rows = [row(1, 10, "in"), row(2, 10, "out", profit="1")]
    rows[1]["reason"] = 4
    result = run(metrics, rows)
    assert result["exit_reasons"]["stop_loss"] == 1
    assert result["complete_trades"]["wins"] == 1


def test_overlapping_positions_and_exact_decimal_exposure(metrics):
    rows = [row(1, 10, "in", volume="0.01"), row(2, 20, "in", volume="0.02"),
            row(3, 10, "out", volume="0.01"), row(4, 20, "out", volume="0.02")]
    result = run(metrics, rows)
    assert result["overlap"]["peak_positions"] == 2
    assert result["overlap"]["peak_lots_by_symbol"]["XAUUSD"] == "0.03"


def test_decimal_precision_preserves_small_fees_next_to_large_profit(metrics):
    result = run(metrics, [row(1, 10, "in", commission="-0.00000001"),
                           row(2, 10, "out", profit="1000000000000000000.01", commission="-0.00000001")])
    assert result["history_totals"]["net"] == "1000000000000000000.00999998"


def test_same_millisecond_exposure_is_marked_ambiguous(metrics):
    result = run(metrics, [row(1, 10, "in", stamp=BASE + 1000), row(2, 10, "out", stamp=BASE + 1000)])
    assert result["counts"]["complete_trades"] == 1
    assert result["overlap"]["available"] is False


def test_non_trade_cash_records_do_not_become_ea_profit(metrics):
    deposit = row(1, 0, "in", volume="0", profit="1000", commission="0")
    deposit["type"] = "balance"
    result = run(metrics, [deposit])
    assert result["counts"]["non_trade_records"] == 1
    assert result["history_totals"]["net"] == "0"
    assert result["non_trade_net_excluded"] == "1000"


def test_inconsistent_entry_code_refuses_summary(metrics):
    item = row(1, 10, "in"); item["entry_code"] = 1
    with pytest.raises(ValueError, match="entry"):
        run(metrics, [item])


def test_contradictory_deal_direction_is_not_a_completed_trade(metrics):
    first = row(1, 10, "in"); last = row(2, 10, "out"); last["type"] = "buy"
    result = run(metrics, [first, last])
    assert result["counts"]["complete_trades"] == 0
    assert result["groups"][0]["status"] == "ambiguous"


def test_conflicting_open_snapshot_is_not_verified(metrics):
    first = {"identifier": 10, "magic": 151515, "symbol": "XAUUSD", "type": "buy",
             "volume": "0.03", "profit": "0", "swap": "0"}
    other = dict(first, volume="0.04")
    with pytest.raises(ValueError, match="Conflicting"):
        run(metrics, [], [first, other])


def completed_rows(outcomes):
    rows = []
    for index, (direction, net) in enumerate(outcomes):
        first = row(index * 2 + 1, index + 1, "in", commission="0")
        last = row(index * 2 + 2, index + 1, "out", profit=net, commission="0")
        first["type"] = direction
        last["type"] = "sell" if direction == "buy" else "buy"
        rows.extend((first, last))
    return rows


def test_positive_direction_net_does_not_imply_all_winners(metrics):
    result = run(metrics, completed_rows([("buy", "100"), ("buy", "-25"),
                                          ("sell", "5"), ("sell", "-20"), ("sell", "-30")]))
    stats = result["complete_trades"]
    buy, sell = stats["by_direction"]["buy"], stats["by_direction"]["sell"]
    assert buy["net"] == "75" and buy["outcome_mix"] == "mixed"
    assert (buy["count"], buy["wins"], buy["losses"], buy["breakeven"]) == (2, 1, 1, 0)
    assert sell["net"] == "-45" and sell["outcome_mix"] == "mixed"
    assert (sell["count"], sell["wins"], sell["losses"]) == (3, 1, 2)
    assert stats["average_win_net"] == "52.5"
    assert stats["average_loss_net_abs"] == "25"
    assert stats["average_win_to_average_loss_ratio"] == "2.1"
    assert stats["average_wins_to_cover_average_loss"] == "0.4762"
    assert stats["average_net_per_position"] == "6"


@pytest.mark.parametrize("profits,mix,wins,losses,breakeven", [
    (["5", "10"], "all_wins", 2, 0, 0), (["-5", "-10"], "all_losses", 0, 2, 0),
    (["0", "0"], "breakeven_only", 0, 0, 2), ([], "no_trades", 0, 0, 0),
    (["5", "0"], "mixed", 1, 0, 1),
])
def test_one_sided_or_zero_sample_does_not_invent_payoff_ratio(metrics, profits, mix, wins, losses, breakeven):
    result = run(metrics, completed_rows([("buy", value) for value in profits]))
    stats = result["complete_trades"]
    assert stats["outcome_mix"] == mix
    assert (stats["wins"], stats["losses"], stats["breakeven"]) == (wins, losses, breakeven)
    assert stats["average_win_to_average_loss_ratio"] is None
    assert stats["average_wins_to_cover_average_loss"] is None
    assert (stats["average_win_net"] is None) == (wins == 0)
    assert (stats["average_loss_net_abs"] is None) == (losses == 0)
    assert stats["by_direction"]["sell"]["outcome_mix"] == "no_trades"


def test_average_denominators_exclude_breakevens_but_net_average_includes_them(metrics):
    stats = run(metrics, completed_rows([("buy", "10"), ("buy", "20"),
                                        ("sell", "-6"), ("sell", "0")]))["complete_trades"]
    assert stats["average_win_net"] == "15" and stats["average_loss_net_abs"] == "6"
    assert stats["average_net_per_position"] == "6"
    assert stats["average_wins_to_cover_average_loss"] == "0.4"
    assert stats["by_direction"]["sell"]["average_loss_net_abs"] == "6"
    assert stats["by_direction"]["sell"]["breakeven"] == 1


def test_direction_outcomes_use_net_after_all_costs(metrics):
    rows = completed_rows([("buy", "1")])
    rows[0]["commission"] = "-0.5"; rows[1]["commission"] = "-0.5"; rows[1]["fee"] = "-0.1"
    stats = run(metrics, rows)["complete_trades"]["by_direction"]["buy"]
    assert stats["net"] == "-0.1" and stats["outcome_mix"] == "all_losses"
    assert stats["wins"] == 0 and stats["losses"] == 1
    assert stats["average_loss_net_abs"] == "0.1"


def test_partial_and_boundary_groups_do_not_enter_direction_averages(metrics):
    rows = completed_rows([("buy", "10")]) + [row(5, 10, "out", profit="1000"),
            row(6, 20, "in"), row(7, 20, "out", volume="0.01", profit="1000")]
    stats = run(metrics, rows)["complete_trades"]
    assert stats["count"] == 1 and stats["average_win_net"] == "10"
    assert stats["by_direction"]["buy"]["count"] == 1


def test_nonzero_tiny_average_and_ratio_do_not_round_to_a_false_zero(metrics):
    stats = run(metrics, completed_rows([("buy", "0.0000000001"), ("buy", "-1")]))["complete_trades"]
    assert stats["average_win_net"] == "0.0000000001"
    assert stats["average_win_to_average_loss_ratio"] == "0.0000000001"
    assert stats["average_wins_to_cover_average_loss"] == "10000000000"


def test_code_built_report_preserves_mixed_direction_and_amount_ratio(metrics):
    receipt = run(metrics, completed_rows([("buy", "100"), ("buy", "-25"),
                                           ("sell", "5"), ("sell", "-20"), ("sell", "-30")]))
    report = receipt["descriptive_report"]
    assert "buy in this sample: 2 positions; 1 wins; 1 losses; 0 breakeven; net 75; outcome mix mixed." in report
    assert "mean-loss-magnitude / mean-win ratio: 0.4762" in report
    assert receipt["scope"]["from_utc"] in report and receipt["scope"]["to_utc"] in report
    assert "expert" in report and "stop-loss" in report


def test_report_with_no_completed_positions_keeps_undefined_means_explicit(metrics):
    receipt = run(metrics, [row(1, 10, "in")])
    report = receipt["descriptive_report"]
    assert "Complete in-window positions: 0; wins 0; losses 0" in report
    assert "Mean winning-position net: None" in report
    assert "outcome mix no_trades" in report


def test_bounded_conclusions_preserve_both_outcomes_despite_positive_net(metrics):
    receipt = run(metrics, completed_rows([("buy", "100"), ("buy", "-25")]))
    notes = receipt["bounded_conclusions"]
    buy = next(note for note in notes if note.startswith("buy in this sample:"))
    assert "net 75, with 1 winning, 1 losing and 0 breakeven" in buy
    assert "Outcome mix: mixed" in buy
    reasons = next(note for note in notes if note.startswith("Exit-deal reasons"))
    assert "expert" in reasons and "An exit reason is not an outcome" in reasons
