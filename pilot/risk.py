from datetime import datetime

from .broker import floor_qty


class Risk:
    """Hard-coded limits. Nothing (including the LLM) can override these."""

    def __init__(self, cfg, journal, tz):
        self.c, self.j, self.tz = cfg, journal, tz

    @property
    def halted(self):
        return bool(self.j.kv_get("halted", False))

    def update(self, equity):
        day = datetime.now(self.tz).strftime("%Y-%m-%d")
        if self.j.kv_get("day") != day:
            self.j.kv_set("day", day)
            self.j.kv_set("day_start_equity", equity)
        peak = max(self.j.kv_get("peak_equity", equity), equity)
        self.j.kv_set("peak_equity", peak)
        if not self.halted and equity <= peak * (1 - self.c["kill_switch_drawdown"]):
            self.j.kv_set("halted", True)
            self.j.event("alert", "KILL SWITCH: drawdown limit hit, closing all and halting",
                         equity=equity, peak=peak)

    def daily_blocked(self, equity):
        start = self.j.kv_get("day_start_equity", equity)
        return equity <= start * (1 - self.c["daily_loss_limit"])

    def size(self, equity, entry, stop, fx, fee, exposure_tmn, free_cash_tmn, info):
        loss_unit = (entry * (1 + fee) - stop * (1 - fee)) * fx
        if loss_unit <= 0:
            return None, 0, "invalid stop"
        qty = equity * self.c["risk_per_trade"] / loss_unit
        cap = min(max(0.0, equity * self.c["max_exposure"] - exposure_tmn), free_cash_tmn / (1 + fee))
        if qty * entry * fx > cap:
            qty = cap / (entry * fx)
        qty = floor_qty(qty, info["qty_dp"])
        notional = qty * entry * fx
        min_n = max(self.c["min_order_tmn"], info["min_notional"] * fx)
        if qty <= 0 or notional < min_n:
            return None, 0, f"size too small ({notional:,.0f} < {min_n:,.0f} TMN) or exposure/cash cap reached"
        return qty, qty * loss_unit, "ok"

    def fee_gate(self, entry, tp, fee):
        move = (tp - entry) / entry
        need = self.c["min_move_fee_multiple"] * 2 * fee
        return move >= need, f"expected move {move:.2%} vs needed {need:.2%}"
