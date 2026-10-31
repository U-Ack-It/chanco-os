"""Mechanic in a throwaway git repo: good repairs are kept and committed, bad ones roll back."""
import os, sys, subprocess, tempfile, unittest, textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import mechanic

def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

def write(path, text):
    with open(path, "w") as f:
        f.write(text)

class Mechanic(unittest.TestCase):
    def setUp(self):
        self._nested = os.environ.pop("CHANCO_MECHANIC_NESTED", None)   # these tests need the Mechanic's real test step
        self.addCleanup(lambda: self._nested and os.environ.__setitem__("CHANCO_MECHANIC_NESTED", self._nested))
        self.d = tempfile.mkdtemp(prefix="chanco_mech_")
        os.makedirs(os.path.join(self.d, "tests"))
        write(os.path.join(self.d, "tool.py"), "def double(x):\n    return x * 2\n")
        write(os.path.join(self.d, "server.py"), "PORT = 9999\n")
        write(os.path.join(self.d, "tests", "test_tool.py"), textwrap.dedent("""
            import os, sys, unittest
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import tool
            class T(unittest.TestCase):
                def test_double(self): self.assertEqual(tool.double(3), 6)
        """))
        for c in (["git", "init", "-q"], ["git", "add", "-A"],
                  ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
            sh(c, self.d)
        self.tool = os.path.join(self.d, "tool.py")

    def apply(self, path, old, new):
        return mechanic.apply(path, old, new, actor="test", repo=self.d, restart=False)

    def test_good_repair_is_kept_and_committed(self):
        r = self.apply(self.tool, "    return x * 2\n", "    return x + x\n")
        self.assertEqual(r["status"], "done", r["message"])
        self.assertIn("x + x", open(self.tool).read())
        self.assertIn("Mechanic (test)", sh(["git", "log", "-1", "--format=%s"], self.d).stdout)

    def test_repair_that_breaks_tests_is_rolled_back(self):
        r = self.apply(self.tool, "    return x * 2\n", "    return x * 3\n")
        self.assertEqual(r["status"], "failed")
        self.assertIn("x * 2", open(self.tool).read())

    def test_syntax_error_changes_nothing(self):
        r = self.apply(self.tool, "    return x * 2\n", "    return (x * 2\n")
        self.assertEqual(r["status"], "failed")
        self.assertIn("x * 2", open(self.tool).read())

    def test_ambiguous_text_is_refused(self):
        with open(self.tool, "a") as f:
            f.write("y = 1\ny = 1\n")
        r = self.apply(self.tool, "y = 1\n", "y = 2\n")
        self.assertEqual(r["status"], "failed")
        self.assertIn("2 times", r["message"])

    def test_server_file_becomes_a_proposal(self):
        srv = os.path.join(self.d, "server.py")
        r = self.apply(srv, "PORT = 9999\n", "PORT = 9998\n")
        self.assertEqual(r["status"], "proposed", r["message"])
        self.assertIn("9999", open(srv).read())                    # not changed live
        self.assertTrue(os.listdir(os.path.join(self.d, "proposals")))

    def test_server_parts_and_mechanic_itself_become_proposals(self):
        for name in ("server.py", "mechanic.py"):
            p = os.path.join(self.d, name)
            write(p, "LIMIT = 1\n")
            r = self.apply(p, "LIMIT = 1\n", "LIMIT = 2\n")
            self.assertEqual(r["status"], "proposed", f"{name}: {r['message']}")
            self.assertIn("LIMIT = 1", open(p).read(), f"{name} was changed live")

if __name__ == "__main__":
    unittest.main()
