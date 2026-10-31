"""The gate's rules: what agents may read, patch and spend. Runs in a throwaway project folder."""
import os, sys, importlib, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.path.realpath(tempfile.mkdtemp(prefix="gate_project_"))
        cls.notes = os.path.realpath(tempfile.mkdtemp(prefix="gate_notes_"))
        cls.outside = os.path.realpath(tempfile.mkdtemp(prefix="gate_outside_"))
        os.environ.update(CHANCO_BASE=cls.base, CHANCO_READ_ROOTS=cls.notes, CHANCO_DAILY_BUDGET="1.00")
        sys.path.insert(0, REPO)
        import gate
        cls.g = importlib.reload(gate)

    @classmethod
    def tearDownClass(cls):
        for k in ("CHANCO_BASE", "CHANCO_READ_ROOTS", "CHANCO_DAILY_BUDGET"):
            os.environ.pop(k, None)

    def p(self, root, *parts):
        return os.path.join(root, *parts)

    def test_reads(self):
        g = self.g
        self.assertTrue(g.can_read(self.p(self.base, "notes.md"))[0])
        self.assertTrue(g.can_read(self.p(self.notes, "book.md"))[0], "extra read folder")
        self.assertFalse(g.can_read(self.p(self.base, "claude_key.txt"))[0], "secret-looking name")
        self.assertFalse(g.can_read(self.p(self.base, ".env"))[0])
        self.assertFalse(g.can_read(self.p(self.outside, "x.md"))[0], "outside the allowed folders")
        self.assertFalse(g.can_read(self.p(self.base, "..", "..", "etc", "passwd"))[0], "../ climbing")
        self.assertFalse(g.can_read("~/.ssh/id_ed25519")[0])

    def test_patches(self):
        g = self.g
        self.assertTrue(g.can_patch(self.p(self.base, "tool.py"))[0])
        self.assertFalse(g.can_patch(self.p(self.base, "dashboard.html"))[0], "only .py files")
        self.assertFalse(g.can_patch(self.p(self.notes, "x.py"))[0], "read-only folder")
        self.assertFalse(g.can_patch("~/.bashrc")[0])

    def test_agent_cannot_edit_its_own_rules(self):
        g = self.g
        self.assertFalse(g.can_patch(self.p(self.base, "gate.py"))[0], "gate.py must be protected")
        self.assertFalse(g.can_patch(self.p(self.base, "config.py"))[0], "config.py must be protected")

    def test_budget(self):
        g = self.g
        usd = g.spend("claude", "claude-sonnet-5", {"input_tokens": 1000, "output_tokens": 1000}, actor="test")
        self.assertAlmostEqual(usd, 0.012, places=6)
        self.assertTrue(g.budget_ok(0.10)[0])
        self.assertFalse(g.budget_ok(5.00)[0])
        self.assertGreater(g.cost("some-unknown-model", 1000, 0), 0)   # an unknown model is never free

    def test_audit_trail(self):
        g = self.g
        g.audit("test", "read_file", "notes.md", allowed=False, reason="demo")
        last = open(g.AUDIT).read().strip().splitlines()[-1]
        self.assertIn('"allowed": false', last)

if __name__ == "__main__":
    unittest.main()
