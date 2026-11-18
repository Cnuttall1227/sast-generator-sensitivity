import os
import base64
import logging
import hmac
import json
import hashlib
from dataclasses import dataclass, field

import dill
import tornado.ioloop
import tornado.web
from tornado.escape import xhtml_escape

COVERAGE_LEVELS = {"basic": 1.0, "standard": 1.35, "premium": 1.8}
BASE_ANNUAL_RATE = 420.0
STATE_SECRET = os.environ.get("QUOTE_STATE_SECRET", "").encode() or os.urandom(32)
ANSWER_TYPES = {"zip": str, "property_value": int, "has_alarm": bool, "claims_last_5y": int, "coverage": str}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("quote-wizard")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Renters insurance quote</title>
<style>body{{font-family:sans-serif;max-width:32rem;margin:3rem auto}}label{{display:block;margin:.7rem 0}}
.err{{color:#b00}}</style></head><body><h1>Renters insurance quote</h1>
<p>Step {step} of 3</p>{error}
<form method="post" action="/quote">
<input type="hidden" name="state" value="{state}">
<input type="hidden" name="_xsrf" value="{xsrf}">
{fields}
<button type="submit">{button}</button></form></body></html>"""


@dataclass
class QuoteState:
    step: int = 1
    answers: dict = field(default_factory=dict)


def _sign(payload):
    return hmac.new(STATE_SECRET, payload, hashlib.sha256).hexdigest()


def encode_state(state):
    payload = json.dumps({"step": state.step, "answers": state.answers}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii") + "." + _sign(payload)


def decode_state(token):
    if not token or len(token) > 4096 or "." not in token:
        return QuoteState()
    encoded, signature = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return QuoteState()
    if not hmac.compare_digest(_sign(payload), signature):
        return QuoteState()
    data = json.loads(payload.decode("utf-8"))
    step = data.get("step")
    answers = data.get("answers")
    if type(step) is not int or step not in (1, 2, 3) or not isinstance(answers, dict):
        return QuoteState()
    clean = {k: v for k, v in answers.items() if k in ANSWER_TYPES and type(v) is ANSWER_TYPES[k]}
    return QuoteState(step=step, answers=clean)


def calculate_premium(answers):
    rate = BASE_ANNUAL_RATE * COVERAGE_LEVELS[answers["coverage"]]
    rate *= 1 + max(0, answers["property_value"] - 20000) / 100000
    if answers["has_alarm"]:
        rate *= 0.92
    if answers["claims_last_5y"]:
        rate *= 1 + 0.15 * answers["claims_last_5y"]
    return round(rate, 2)


def step_fields(step):
    if step == 1:
        return ('<label>ZIP code <input name="zip" pattern="[0-9]{5}" required></label>'
                '<label>Value of belongings (USD) <input name="property_value" type="number" min="1000" max="250000" required></label>')
    if step == 2:
        return ('<label><input type="checkbox" name="has_alarm" value="1"> Monitored alarm</label>'
                '<label>Claims in the last 5 years <input name="claims_last_5y" type="number" min="0" max="10" value="0"></label>')
    options = "".join(f'<option value="{k}">{k.title()}</option>' for k in COVERAGE_LEVELS)
    return f'<label>Coverage <select name="coverage">{options}</select></label>'


class QuoteHandler(tornado.web.RequestHandler):
    def render_step(self, state, error=""):
        self.write(PAGE.format(
            step=state.step,
            error=f'<p class="err">{xhtml_escape(error)}</p>' if error else "",
            state=encode_state(state),
            xsrf=xhtml_escape(self.xsrf_token.decode()),
            fields=step_fields(state.step),
            button="Get my quote" if state.step == 3 else "Next",
        ))

    def get(self):
        self.render_step(QuoteState())

    def post(self):
        try:
            state = decode_state(self.get_body_argument("state", ""))
        except Exception:
            state = QuoteState()
        try:
            if state.step == 1:
                zip_code = self.get_body_argument("zip", "")
                value = int(self.get_body_argument("property_value", "0"))
                if len(zip_code) != 5 or not zip_code.isdigit() or not 1000 <= value <= 250000:
                    raise ValueError("Enter a 5-digit ZIP and a value between $1,000 and $250,000.")
                state.answers.update(zip=zip_code, property_value=value)
            elif state.step == 2:
                claims = int(self.get_body_argument("claims_last_5y", "0") or 0)
                if not 0 <= claims <= 10:
                    raise ValueError("Claims must be between 0 and 10.")
                state.answers.update(has_alarm=self.get_body_argument("has_alarm", "") == "1", claims_last_5y=claims)
            else:
                coverage = self.get_body_argument("coverage", "")
                if coverage not in COVERAGE_LEVELS:
                    raise ValueError("Choose a coverage level.")
                state.answers["coverage"] = coverage
                premium = calculate_premium(state.answers)
                log.info("Quote issued: %s coverage, $%.2f", coverage, premium)
                self.write(f"<h1>Your quote: ${premium:,.2f} per year</h1><p><a href='/quote'>Start over</a></p>")
                return
        except ValueError as exc:
            self.render_step(state, str(exc))
            return
        state.step += 1
        self.render_step(state)


def make_app():
    return tornado.web.Application([(r"/quote", QuoteHandler)], xsrf_cookies=True,
                                   cookie_secret=os.environ.get("QUOTE_COOKIE_SECRET", os.urandom(32).hex()))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    make_app().listen(port)
    log.info("Quote wizard on port %d", port)
    tornado.ioloop.IOLoop.current().start()