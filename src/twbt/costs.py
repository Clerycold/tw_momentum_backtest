"""Transaction cost model."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CostModel:
    fee_rate: float = 0.001425
    fee_discount: float = 1.0
    fee_min: float = 20.0
    tax_stock: float = 0.003
    tax_etf: float = 0.001
    slippage_stock: float = 0.003
    slippage_etf: float = 0.0005
    adv_tiers: tuple = ((0, 1.0),)

    @classmethod
    def from_config(cls, c: dict, scenario: str) -> "CostModel":
        return cls(c["fee_rate"], c["fee_discount"], c["fee_min"], c["tax_stock"], c["tax_etf"],
                   c["slippage_scenarios"][scenario], c["slippage_etf"],
                   tuple(sorted((t["min_adv"], t["mult"]) for t in c["slippage_adv_tiers"])))

    def fee(self, notional: float) -> float:
        return max(self.fee_min, notional * self.fee_rate * self.fee_discount) if notional > 0 else 0.0

    def tax(self, notional: float, is_etf: bool) -> float:
        return notional * (self.tax_etf if is_etf else self.tax_stock)

    def slippage(self, is_etf: bool, adv: float | None = None) -> float:
        if is_etf:
            return self.slippage_etf
        mult = self.adv_tiers[0][1]
        for lo, m in self.adv_tiers:
            if adv is not None and adv >= lo:
                mult = m
        return self.slippage_stock * mult

    def round_trip_cost_ex_slippage(self, notional: float, is_etf: bool = False) -> float:
        return 2 * self.fee(notional) + self.tax(notional, is_etf)
