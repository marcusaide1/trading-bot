"""Notification dispatcher for Telegram and Discord webhooks."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from bot.monitoring.logger import get_logger

logger = get_logger("alerts")


class AlertManager:
    """Fail-safe alert sender so notification errors never disrupt trading execution."""

    def __init__(
        self,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
        timeout: float = 5.0,
    ) -> None:
        self.telegram_bot_token = telegram_bot_token.strip()
        self.telegram_chat_id = telegram_chat_id.strip()
        self.discord_webhook_url = discord_webhook_url.strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(
            (self.telegram_bot_token and self.telegram_chat_id)
            or self.discord_webhook_url
        )

    def send(self, title: str, message: str, severity: str = "INFO") -> bool:
        """Send an alert to all configured channels. Returns True if at least one succeeded."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        formatted = f"[{severity.upper()}] {title}\n{message}\nTime: {timestamp}"

        if not self.enabled:
            logger.debug("Alert (no channel configured): %s - %s", title, message)
            return False

        sent_any = False

        if self.telegram_bot_token and self.telegram_chat_id:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            try:
                resp = httpx.post(
                    url,
                    json={"chat_id": self.telegram_chat_id, "text": formatted},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                sent_any = True
            except Exception as exc:
                logger.warning("Failed to dispatch Telegram alert: %s", exc)

        if self.discord_webhook_url:
            try:
                resp = httpx.post(
                    self.discord_webhook_url,
                    json={"content": f"```\n{formatted}\n```"},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                sent_any = True
            except Exception as exc:
                logger.warning("Failed to dispatch Discord alert: %s", exc)

        return sent_any

    def notify_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        pnl: float | None = None,
        reason: str = "",
    ) -> bool:
        lines = [
            f"Symbol: {symbol}",
            f"Side: {side.upper()}",
            f"Qty: {quantity:.6f} @ ${price:,.4f}",
        ]
        if pnl is not None:
            lines.append(f"Realized PnL: ${pnl:+,.2f}")
        if reason:
            lines.append(f"Reason: {reason}")
        return self.send("Trade Executed", "\n".join(lines), severity="INFO")

    def notify_risk_halt(self, reason: str, equity: float, drawdown_pct: float) -> bool:
        body = (
            f"Trading HALTED by Risk Circuit Breaker!\n"
            f"Reason: {reason}\n"
            f"Current Equity: ${equity:,.2f}\n"
            f"Drawdown: {drawdown_pct * 100:.2f}%"
        )
        return self.send("RISK CIRCUIT BREAKER", body, severity="CRITICAL")
