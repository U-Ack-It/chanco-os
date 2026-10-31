"""
mechanic.py: safe self-repair for an AI agent system.

Every repair follows the same path:
  1. the gate decides if the file may be patched (gate.py and config.py never)
  2. the old text must appear EXACTLY once (no accidental mass replace)
  3. the server's parts and mechanic.py itself are never changed live: the fix is saved as a PROPOSAL you approve
  4. otherwise: write -> syntax check -> run the test suite -> keep only if all tests pass, else restore
  5. a kept fix is committed in git as "Mechanic" (one command undoes it: git revert)
  6. a fix to a running service restarts that service

Proposals (from the command line):
  python3 mechanic.py --list            show pending proposals with their diff
  python3 mechanic.py --apply <id>      apply one (same safety path), then restart the server
  python3 mechanic.py --reject <id>     discard one
"""
import os, sys, json, glob, difflib, datetime, subprocess
import gate

REPO = os.path.dirname(os.path.abspath(__file__))
# The running server and the Mechanic's own rules are never edited live: a human approves a proposal.
# Edit these two settings for your project.
SERVER_PARTS = {"server.py"}                       # files the live server is made of
LIVE_ONLY_BY_PROPOSAL = SERVER_PARTS | {"mechanic.py"}
SERVICE_OF = {}                                    # optional: {"worker.py": "my-worker"} -> systemctl --user restart my-worker

def _run(cmd, repo, timeout=180):
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)

def _tests_pass(repo):
    if os.environ.get("CHANCO_MECHANIC_NESTED"):
        return True, "inside a test run already"          # the outer test suite is the judge; no recursion
    if not os.path.isdir(os.path.join(repo, "tests")):
        return True, "no tests folder"
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=repo,
                       capture_output=True, text=True, timeout=180, env=dict(os.environ, CHANCO_MECHANIC_NESTED="1"))
    tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
    return r.returncode == 0, " | ".join(tail)

def _diff(path, old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{os.path.basename(path)}", f"b/{os.path.basename(path)}"))

def _write_proposal(path, old_text, new_text, actor, repo):
    pdir = os.path.join(repo, "proposals"); os.makedirs(pdir, exist_ok=True)
    pid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json.dump({"id": pid, "file": os.path.basename(path), "actor": actor, "diff": _diff(path, old_text, new_text),
               "new_content": new_text}, open(os.path.join(pdir, f"{pid}.json"), "w"), indent=1)
    return pid

def _commit_and_restart(path, repo, actor, restart=True):
    name = os.path.basename(path)
    committed = False
    if os.path.realpath(path).startswith(os.path.realpath(repo) + os.sep):   # only files that live in this repo
        _run(["git", "add", "--", name], repo)
        c = _run(["git", "-c", "user.name=Mechanic", "-c", "user.email=mechanic@localhost",
                  "commit", "-q", "-m", f"Mechanic ({actor}): repair {name}", "--", name], repo)   # commits ONLY this file
        committed = c.returncode == 0
    svc = SERVICE_OF.get(name)
    if restart and svc:
        _run(["systemctl", "--user", "restart", svc], repo, timeout=60)
    return committed, svc

def apply(path, old_string, new_string, actor="chanco", repo=REPO, restart=True):
    """Returns {"status": "done"|"proposed"|"failed", "message": "..."}"""
    ok, real = gate.can_patch(path) if repo == REPO else (path.endswith(".py"), os.path.realpath(path))
    if not ok:
        gate.audit(actor, "mechanic", path, False, "blocked by gate")
        return {"status": "failed", "message": "Blocked by the gate: the Mechanic may only repair .py files in the project, never gate.py or config.py."}
    original = open(real, encoding="utf-8").read()
    n = original.count(old_string) if old_string else 0
    if n != 1:
        return {"status": "failed", "message": f"The text to replace appears {n} times; it must appear exactly once. Nothing changed."}
    patched = original.replace(old_string, new_string, 1)
    try:
        compile(patched, real, "exec")
    except SyntaxError as e:
        return {"status": "failed", "message": f"Syntax error in the repair (line {e.lineno}: {e.msg}). Nothing changed."}

    if os.path.basename(real) in LIVE_ONLY_BY_PROPOSAL:
        pid = _write_proposal(real, original, patched, actor, repo)
        gate.audit(actor, "mechanic_proposal", f"{real} #{pid}", True)
        return {"status": "proposed", "message": f"Repair saved as proposal {pid}. Review: python3 mechanic.py --list ; apply: python3 mechanic.py --apply {pid}"}

    open(real, "w", encoding="utf-8").write(patched)
    passed, summary = _tests_pass(repo)
    if not passed:
        open(real, "w", encoding="utf-8").write(original)          # roll back
        gate.audit(actor, "mechanic", real, False, "tests failed, rolled back")
        return {"status": "failed", "message": f"Repair broke the tests, so it was rolled back. Tests said: {summary}"}
    committed, svc = _commit_and_restart(real, repo, actor, restart)
    gate.audit(actor, "mechanic", real, True, "tests passed, committed")
    return {"status": "done", "message": f"Repaired {os.path.basename(real)}: tests pass" + (", saved in git" if committed else "")
            + (f", {svc} restarted" if svc and restart else "") + ". Undo: git revert HEAD"}

# ---------- proposals ----------
def _cli():
    pdir = os.path.join(REPO, "proposals")
    files = sorted(glob.glob(os.path.join(pdir, "*.json")))
    if "--list" in sys.argv:
        if not files:
            print("No pending proposals.")
        for f in files:
            p = json.load(open(f))
            print(f"=== {p['id']}  {p['file']}  (by {p['actor']})\n{p['diff']}")
    elif "--apply" in sys.argv or "--reject" in sys.argv:
        pid = sys.argv[-1]; f = os.path.join(pdir, f"{pid}.json")
        if not os.path.exists(f):
            sys.exit(f"No proposal {pid}. See: python3 mechanic.py --list")
        p = json.load(open(f))
        if "--reject" in sys.argv:
            os.rename(f, f + ".rejected"); print(f"Proposal {pid} rejected (kept as {os.path.basename(f)}.rejected)."); return
        target = os.path.join(REPO, p["file"])
        original = open(target, encoding="utf-8").read()
        open(target, "w", encoding="utf-8").write(p["new_content"])
        passed, summary = _tests_pass(REPO)
        if not passed:
            open(target, "w", encoding="utf-8").write(original)
            sys.exit(f"Tests failed, proposal NOT applied (file restored). Tests said: {summary}")
        committed, svc = _commit_and_restart(target, REPO, "you (proposal)")
        os.rename(f, f + ".applied")
        gate.audit("you", "mechanic_apply_proposal", f"{p['file']} #{pid}", True)
        print(f"Applied {pid}: tests pass, {'saved in git, ' if committed else ''}{svc or 'nothing'} restarted. Undo: git revert HEAD")
    else:
        print(__doc__)

if __name__ == "__main__":
    _cli()
