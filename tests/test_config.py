"""Config loading: example file, validation, CLI-selected markets.

Run:  python3 -m pytest tests/  (or  python3 tests/test_config.py)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lighter_arb.config import ConfigError, load_config  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
EXAMPLE = os.path.join(ROOT, "config.example.yaml")
NO_ENV = os.path.join(tempfile.gettempdir(), "lighter-arb-no-such.env")


def write_tmp(text: str) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    f.write(text)
    f.close()
    return f.name


MINIMAL = """
thresholds:
  midline_bps: 5.0
  upper_bps: 4.0
  lower_bps: 3.0
"""


def load(yaml_text: str, symbol="BTC", base="lighter", hedge="lighter-rh"):
    return load_config(write_tmp(yaml_text), NO_ENV,
                       symbol=symbol, base_venue=base, hedge_venue=hedge)


def test_example_config_loads():
    cfg = load_config(EXAMPLE, NO_ENV, symbol="BTC",
                      base_venue="lighter", hedge_venue="lighter-rh")
    assert cfg.symbol == "BTC"
    assert cfg.base_venue == "lighter" and cfg.hedge_venue == "lighter-rh"
    assert cfg.base.lighter_profile.chain_id == 304
    assert cfg.hedge.lighter_profile.chain_id == 466324
    assert cfg.base.symbol == "BTC" and cfg.hedge.symbol == "BTC"
    assert cfg.recorder_enabled and cfg.recorder_csv
    assert cfg.dashboard and cfg.log_file


def test_minimal_defaults():
    cfg = load(MINIMAL)
    assert cfg.midline_bps == 5.0 and cfg.upper_bps == 4.0 and cfg.lower_bps == 3.0
    assert cfg.base.label == "LIGHTER" and cfg.hedge.label == "RH"
    assert cfg.take_fraction == 0.5          # defaults kick in
    assert cfg.recorder_enabled is True
    # Lighter's order ceiling is ~40/min
    assert cfg.base.orders_per_min == 30 and cfg.hedge.orders_per_min == 30


def test_legs_can_swap():
    cfg = load(MINIMAL, base="lighter-rh", hedge="lighter")
    assert cfg.base.label == "RH" and cfg.hedge.label == "LIGHTER"
    assert cfg.base.lighter_profile.chain_id == 466324
    assert cfg.hedge.lighter_profile.chain_id == 304


def test_lighter_vs_lighter_rh():
    """Our pair: Lighter mainnet as the base leg, Robinhood chain as the hedge.

    premium = base / hedge - 1, so this is the l_bid/r_ask premium we record.
    """
    os.environ.update(LIGHTER_ACCOUNT_INDEX="11", LIGHTER_API_KEY_INDEX="2",
                      LIGHTER_API_PRIVATE_KEY="aa",
                      RH_ACCOUNT_INDEX="22", RH_API_KEY_INDEX="3",
                      RH_API_PRIVATE_KEY="bb")
    try:
        cfg = load(MINIMAL, symbol="BTC", base="lighter", hedge="lighter-rh")
        assert cfg.base_venue == "lighter" and cfg.hedge_venue == "lighter-rh"
        assert cfg.base.label == "LIGHTER" and cfg.hedge.label == "RH"
        assert cfg.base.lighter_profile.chain_id == 304
        assert cfg.hedge.lighter_profile.chain_id == 466324
        # each deployment is a separate account with its own key
        assert cfg.base.lighter_creds.account_index == 11
        assert cfg.hedge.lighter_creds.account_index == 22
        assert cfg.base.lighter_creds.api_private_key == "aa"
        assert cfg.hedge.lighter_creds.api_private_key == "bb"
        assert cfg.creds_complete
        assert cfg.base.orders_per_min == 30
    finally:
        for k in ("LIGHTER_ACCOUNT_INDEX", "LIGHTER_API_KEY_INDEX",
                  "LIGHTER_API_PRIVATE_KEY", "RH_ACCOUNT_INDEX",
                  "RH_API_KEY_INDEX", "RH_API_PRIVATE_KEY"):
            os.environ.pop(k, None)


def expect_error(yaml_text: str, needle: str, **kw):
    try:
        load(yaml_text, **kw)
    except ConfigError as e:
        assert needle in str(e), f"{needle!r} not in {e}"
        return
    raise AssertionError(f"expected ConfigError containing {needle!r}")


def test_unknown_key_rejected():
    expect_error(MINIMAL + "\nthresholdz:\n  x: 1\n",
                 "unknown config key 'thresholdz'")
    expect_error(MINIMAL + "\nsizing:\n  take_fractionn: 0.5\n",
                 "sizing.take_fractionn")


def test_markets_no_longer_config_keys():
    # symbol / venues moved to --symbol / --base / --hedge: leftovers in the
    # YAML must fail loudly, not silently override the flags
    expect_error("symbol: BTC\n" + MINIMAL, "unknown config key 'symbol'")
    expect_error("hedge_venue: lighter\n" + MINIMAL,
                 "unknown config key 'hedge_venue'")


def test_bad_cli_markets():
    expect_error(MINIMAL, "--hedge", hedge="binance")
    expect_error(MINIMAL, "--symbol", symbol="")
    expect_error(MINIMAL, "--base", base="binance")
    expect_error(MINIMAL, "same market on both legs",
                 base="lighter-rh", hedge="lighter-rh")


def test_missing_thresholds():
    expect_error("recorder:\n  enabled: true\n", "thresholds.")


def test_nonpositive_band():
    expect_error("thresholds:\n"
                 "  midline_bps: 5\n  upper_bps: 0\n  lower_bps: 3\n",
                 "must be > 0")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name:40s} OK")
