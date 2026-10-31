"""
gate.py: ONE place that decides what AI agents may do. Plain code, never the AI.
Every agent (chat tools, night workers, the self-repair Mechanic) asks the gate before acting.

    import gate
    ok, real = gate.can_read(path)          # allowlist + secret filter
    ok, real = gate.can_patch(path)         # code edits: .py inside the project only, never the rule files
    ok, why  = gate.budget_ok(0.10)         # would this spend stay under today's cap?
    gate.spend("claude", model, usage, actor="ghost")   # record real cost from the API's usage field
    gate.audit("chanco", "read_file", path, allowed=True)
    gate.today()                            # {"spent": 0.42, "cap": 2.0, "calls": 9, "by_actor": {...}}

Settings (environment variables or defaults below):
    CHANCO_BASE           the project folder agents work in (default: the folder that holds gate.py)
    CHANCO_READ_ROOTS     extra folders agents may READ, separated by ":" (default: none)
    CHANCO_DAILY_BUDGET   daily cap in USD for all cloud AI calls together (default 2.00)
"""
import os, re, json, sqlite3, datetime, threading

BASE = os.path.realpath(os.path.expanduser(os.environ.get("CHANCO_BASE", os.path.dirname(os.path.abspath(__file__)))))
LEDGER = os.path.join(BASE, "logs", "gate_ledger.sqlite")
AUDIT = os.path.join(BASE, "logs", "gate_audit.jsonl")
DAILY_BUDGET = float(os.environ.get("CHANCO_DAILY_BUDGET", "2.00"))

# ---------- 1. files ----------
READ_ROOTS = [BASE] + [os.path.realpath(os.path.expanduser(p))
                       for p in os.environ.get("CHANCO_READ_ROOTS", "").split(":") if p]
PATCH_ROOTS = [os.path.realpath(BASE)]
SECRET = re.compile(r"(key|token|secret|passw|cookie|credential|\.env|\.pem|id_rsa|id_ed25519|"
                    r"\.ssh|\.gnupg|keyring|\.db$|\.sqlite)", re.I)

def _inside(real, roots):
    return any(real == r or real.startswith(r + os.sep) for r in roots)

def can_read(path):
    real = os.path.realpath(os.path.expanduser(path or ""))
    return (_inside(real, READ_ROOTS) and not SECRET.search(real)), real

def can_patch(path):
    real = os.path.realpath(os.path.expanduser(path or ""))
    protected = {"gate.py", "config.py"}            # an agent can never loosen its own rules
    return (_inside(real, PATCH_ROOTS) and real.endswith(".py") and not SECRET.search(real)
            and os.path.basename(real) not in protected), real

# ---------- 2. money ----------
# USD per 1M tokens (input, output). Example prices (Oct 2026); edit for your providers.
PRICES = {
    "claude-sonnet-5": (2.00, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "local": (0.0, 0.0),
}
DEFAULT_PRICE = (3.00, 15.00)   # unknown model: assume expensive, so the cap stays safe

_lock = threading.Lock()

def _db():
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    con = sqlite3.connect(LEDGER, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS spend (ts TEXT, day TEXT, actor TEXT, provider TEXT, model TEXT,
                   tokens_in INTEGER, tokens_out INTEGER, usd REAL)""")
    return con

def cost(model, tokens_in, tokens_out):
    pin, pout = PRICES.get(model, DEFAULT_PRICE)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000

def spend(provider, model, usage, actor="unknown"):
    """Record one API call. `usage` is the API's usage dict (OpenAI-style or Anthropic-style). Returns USD."""
    usage = usage or {}
    t_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    t_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    usd = cost(model, t_in, t_out)
    now = datetime.datetime.now()
    with _lock:
        con = _db()
        con.execute("INSERT INTO spend VALUES (?,?,?,?,?,?,?,?)",
                    (now.isoformat(timespec="seconds"), now.date().isoformat(), actor, provider, model, t_in, t_out, usd))
        con.commit(); con.close()
    return usd

def today():
    con = _db()
    day = datetime.date.today().isoformat()
    spent, calls = con.execute("SELECT COALESCE(SUM(usd),0), COUNT(*) FROM spend WHERE day=?", (day,)).fetchone()
    by = dict(con.execute("SELECT actor, ROUND(SUM(usd),4) FROM spend WHERE day=? GROUP BY actor", (day,)).fetchall())
    con.close()
    return {"day": day, "spent": round(spent, 4), "cap": DAILY_BUDGET, "calls": calls, "by_actor": by}

def budget_ok(estimated_usd=0.0):
    t = today()
    if t["spent"] + estimated_usd > DAILY_BUDGET:
        return False, f"Daily AI budget reached (${t['spent']:.2f} of ${DAILY_BUDGET:.2f}). Resumes tomorrow."
    return True, f"${t['spent']:.2f} of ${DAILY_BUDGET:.2f} used today"

# ---------- 3. audit trail ----------
def audit(actor, action, target="", allowed=True, reason=""):
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "actor": actor, "action": action,
           "target": str(target)[:300], "allowed": allowed, "reason": reason}
    with _lock, open(AUDIT, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    t = today()
    print(f"Today {t['day']}: ${t['spent']:.4f} of ${t['cap']:.2f} in {t['calls']} AI calls. By agent: {t['by_actor'] or 'none yet'}")
