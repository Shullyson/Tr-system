"""
Email notifier — sends an alert only when the decision agent actually
produces a verdict. Uses Gmail SMTP with an App Password (not your normal
Gmail password): https://myaccount.google.com/apppasswords

All credentials come from environment variables, never hardcoded.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "config"))
from settings import EMAIL_CONFIG as CFG


class EmailNotifier:
    def __init__(self):
        self.sender = os.environ.get(CFG["sender_env_var"])
        self.app_password = os.environ.get(CFG["app_password_env_var"])
        self.recipient = os.environ.get(CFG["recipient_env_var"])
        self.enabled = bool(self.sender and self.app_password and self.recipient)

    def send_decision_alert(self, decision) -> bool:
        """
        decision: a DecisionOutput from decision_agent.py.
        Returns True if sent, False if email isn't configured (this is
        NOT an error — email is optional, the system should still work
        and print to console without it).
        """
        if not self.enabled:
            return False

        subject = f"[Trading Alert] {decision.verdict.upper()} — {decision.direction.upper()} {decision.symbol}"

        body = f"""Verdict: {decision.verdict}

{decision.symbol} — {decision.direction.upper()}
Entry: {decision.entry_price}
Stop-loss: {decision.stop_loss}
Take-profit: {decision.take_profit}
Reward:risk: {decision.reward_risk_ratio}
Position size: {decision.position_size_units} units (${decision.position_size_usd})
Risk amount: ${decision.risk_amount}

Reasoning:
{decision.explanation}

Agreements: {', '.join(decision.key_agreements) if decision.key_agreements else 'None listed'}
Conflicts: {', '.join(decision.key_conflicts) if decision.key_conflicts else 'None listed'}
Caveats: {', '.join(decision.caveats) if decision.caveats else 'None listed'}

---
This is an advisory alert only. No trade has been placed. Verify
independently before acting — this system does not guarantee accuracy.
"""

        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(CFG["smtp_server"], CFG["smtp_port"]) as server:
                server.starttls()
                server.login(self.sender, self.app_password)
                server.sendmail(self.sender, self.recipient, msg.as_string())
            return True
        except Exception as e:
            print(f"   Email send failed: {e}")
            return False


if __name__ == "__main__":
    from dataclasses import dataclass

    @dataclass
    class MockDecision:
        symbol: str = "BTCUSDT"
        direction: str = "long"
        entry_price: float = 63000
        stop_loss: float = 62250
        take_profit: float = 64500
        reward_risk_ratio: float = 2.0
        position_size_units: float = 0.158
        position_size_usd: float = 10000
        risk_amount: float = 119
        verdict: str = "high_conviction"
        explanation: str = "Test alert — indicator, FA, and TA all agree on bullish bias."
        key_agreements: list = None
        key_conflicts: list = None
        caveats: list = None

    notifier = EmailNotifier()
    if not notifier.enabled:
        print("Email not configured — set ALERT_EMAIL_SENDER, "
              "ALERT_EMAIL_APP_PASSWORD, ALERT_EMAIL_RECIPIENT in .env")
    else:
        sent = notifier.send_decision_alert(MockDecision())
        print("Sent:" if sent else "Failed to send:", sent)
