"""
chunker.py: one way to cut text into memory pieces (for embeddings / RAG), used by every ingest script.

  pieces of at most 1500 characters (stays under the embedding model's ~512-token reading limit)
  each piece ends at a paragraph, sentence, line or word when possible (never mid-word if a space exists)
  each piece repeats the last ~250 characters of the previous one (overlap), so an idea that sits
  on a cut is still found whole in at least one piece

  import chunker
  pieces = chunker.chunk_text(text)
"""
SIZE = 1500
OVERLAP = 250
BREAKS = ("\n\n", ". ", "? ", "! ", ".\n", "\n", "; ", ", ", " ")

def chunk_text(text, size=SIZE, overlap=OVERLAP):
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    overlap = min(overlap, size // 3)
    pieces, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            for sep in BREAKS:                      # best natural break in the second half of the window
                cut = window.rfind(sep)
                if cut >= size // 2:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        nxt = end - overlap                          # step back to make the overlap...
        region = text[nxt:end - 40]                  # ...start it at a sentence if one begins there,
        marks = [region.find(m) for m in (". ", "? ", "! ", "\n")]
        marks = [m for m in marks if m != -1]
        if marks:
            nxt += min(marks) + 2
        else:                                        # ...otherwise at a word, never mid-word
            sp = text.find(" ", nxt, end)
            nxt = sp + 1 if sp != -1 else nxt
        start = nxt if nxt > start else end          # always move forward
    return pieces
