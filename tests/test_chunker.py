"""Memory pieces: short enough to embed, cut at natural breaks, overlapping so no idea is lost on a cut."""
import os, sys, random, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chunker

random.seed(7)
WORDS = "river market ledger harbor archive window record signal garden bridge".split()
def sentence(i):
    return f"Sentence {i} " + " ".join(random.choice(WORDS) for _ in range(random.randint(6, 25))) + "."
DOC = "\n\n".join(" ".join(sentence(p * 100 + s) for s in range(random.randint(3, 9))) for p in range(40))

class Chunker(unittest.TestCase):
    def test_empty_and_short(self):
        self.assertEqual(chunker.chunk_text(""), [])
        self.assertEqual(chunker.chunk_text(None), [])
        self.assertEqual(chunker.chunk_text("  hello  "), ["hello"])

    def test_pieces_are_small_enough(self):
        self.assertTrue(all(len(p) <= chunker.SIZE for p in chunker.chunk_text(DOC)))

    def test_every_sentence_is_whole_in_some_piece(self):
        pieces = chunker.chunk_text(DOC)
        for s in [x for para in DOC.split("\n\n") for x in para.split(". ")]:
            s = s.strip().rstrip(".")
            if len(s) < chunker.OVERLAP:
                self.assertTrue(any(s in p for p in pieces), s[:40])

    def test_old_method_cut_sentences_new_does_not(self):
        old = [DOC[i:i + 2000] for i in range(0, len(DOC), 2000)]
        cut_old = sum(1 for p in old[:-1] if not p.rstrip().endswith("."))
        new = chunker.chunk_text(DOC)
        cut_new = sum(1 for p in new[:-1] if not p.rstrip().endswith("."))
        self.assertGreater(cut_old, 0)
        self.assertEqual(cut_new, 0)

    def test_neighbours_overlap(self):
        pieces = chunker.chunk_text(DOC)
        for a, b in zip(pieces, pieces[1:]):
            self.assertTrue(any(a.endswith(b[:k]) or b[:k] in a for k in (40,)), "no overlap")

    def test_nothing_is_lost(self):
        joined = " ".join(chunker.chunk_text(DOC))
        for w in set(DOC.split()):
            self.assertIn(w, joined)

    def test_text_without_spaces_still_finishes(self):
        pieces = chunker.chunk_text("x" * 10000)
        self.assertTrue(all(len(p) <= chunker.SIZE for p in pieces))
        self.assertGreaterEqual(sum(len(p) for p in pieces), 10000)

if __name__ == "__main__":
    unittest.main()
