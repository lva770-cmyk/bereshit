from dataclasses import dataclass, field

@dataclass
class Battery:
    """Physical and commercial limits of the arbitrage part of the plant."""
    power_mw: float = 80.0          # MW available for arbitrage (100 MW plant minus 20 MW held for aFRR/FCR)
    energy_mwh: float = 320.0       # MWh behind that power (4 h plant -> 80 MW x 4 h)
    rte: float = 0.88               # round-trip efficiency
    max_cycles_per_day: float = 2.0 # full-equivalent discharge cycles (warranty limit)
    wear_eur_per_mwh: float = 3.0   # degradation cost per MWh discharged
    hurdle_eur_per_mwh: float = 0.0 # extra spread demanded before trading on a *forecast* (risk buffer)

@dataclass
class Market:
    zone: str = "HU"                # Energy-Charts bidding-zone code
    country: str = "hu"             # Energy-Charts country code for generation / load
    tz: str = "Europe/Budapest"     # delivery-day time zone (CET/CEST, same as SDAC)
    gate_closure_local: str = "12:00"  # SDAC day-ahead gate closure, D-1

@dataclass
class Settings:
    battery: Battery = field(default_factory=Battery)
    market: Market = field(default_factory=Market)
    forecaster: str = "blend"       # naive | blend | ridge | ridge_fund  (blend won the HU backtest)
    train_days: int = 56            # rolling training window for ridge
    ridge_lambda: float = 1.0
    log_dir: str = "shadow_log"
