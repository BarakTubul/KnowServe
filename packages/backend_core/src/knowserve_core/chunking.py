"""Page-bound chunking with an offline tokenizer (M3-02a, ING-02, OPEN-03, finding F17).

Chunks come from LlamaIndex's ``SentenceSplitter``, run on each page alone, so no chunk ever spans
two pages and every chunk keeps its page number. ``chunk_size_tokens`` and
``chunk_overlap_tokens`` come from ``Settings`` (defaults 512 and 64).

Offline tokenizer. ``SentenceSplitter`` counts tokens with tiktoken, whose vocabulary is normally
downloaded on first use, and its default sentence splitter loads NLTK data that is also fetched.
Neither is acceptable in the Worker: a network read at run time is a failure mode and a supply
chain input. So this module

- loads the ``cl100k_base`` vocabulary (the encoding of ``text-embedding-3-small``) from the file
  bundled in ``knowserve_core/data/`` and checks its SHA-256, and
- passes its own sentence splitter, a regular expression, instead of the NLTK one.

``llama_index`` is imported inside the function, so importing this module stays cheap.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from .pdf_extraction import ExtractedPage

if TYPE_CHECKING:
    import tiktoken

_VOCAB_FILE = Path(__file__).parent / "data" / "cl100k_base.tiktoken"
# SHA-256 of the file OpenAI publishes for cl100k_base (the same value tiktoken checks).
_VOCAB_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
_PAT_STR = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+"""
    r"""|\s++$|\s*[\r\n]|\s+(?!\S)|\s"""
)
_SPECIAL_TOKENS = {
    "<|endoftext|>": 100257,
    "<|fim_prefix|>": 100258,
    "<|fim_middle|>": 100259,
    "<|fim_suffix|>": 100260,
    "<|endofprompt|>": 100276,
}


@dataclass(frozen=True)
class Chunk:
    """One chunk of one page. ``ordinal`` is 0-based and contiguous over the whole revision,
    ``page_number`` is 1-based, ``token_count`` is at least 1."""

    ordinal: int
    page_number: int
    text: str
    token_count: int


@lru_cache(maxsize=1)
def get_encoding() -> tiktoken.Encoding:
    """The ``cl100k_base`` tokenizer, built from the bundled vocabulary. Never uses the network."""
    import tiktoken

    raw = _VOCAB_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _VOCAB_SHA256:
        raise RuntimeError("bundled tokenizer vocabulary is corrupt")
    ranks: dict[bytes, int] = {}
    for line in raw.splitlines():
        if line:
            token, rank = line.split()
            ranks[base64.b64decode(token)] = int(rank)
    return tiktoken.Encoding(
        name="cl100k_base",
        pat_str=_PAT_STR,
        mergeable_ranks=ranks,
        special_tokens=_SPECIAL_TOKENS,
    )


def count_tokens(text: str) -> int:
    """Token count of ``text``. Special-token look-alikes such as ``<|endoftext|>`` in a document
    are ordinary text here and never raise."""
    return len(get_encoding().encode_ordinary(text))


# Sentence ends: . ! ? (and their CJK and Arabic forms) plus closing quotes or brackets, then
# whitespace. The pieces keep their whitespace, so joining them gives the original text back.
_SENTENCE = re.compile(r".*?(?:[.!?。！？؟]+[\"'”’)\]]*\s+|\Z)", re.DOTALL)


def split_sentences(text: str) -> list[str]:
    return [piece for piece in _SENTENCE.findall(text) if piece]


def chunk_pages(
    pages: Sequence[ExtractedPage],
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> list[Chunk]:
    """Split ``pages`` into chunks. Pages are chunked one at a time, so a chunk lies inside one
    page. Empty pages produce nothing. Ordinals run 0, 1, 2, ... over the result in page order.
    Deterministic: the same input and sizes always give the same chunks.

    Raises ``ValueError`` if ``chunk_overlap_tokens >= chunk_size_tokens`` (``Settings`` already
    refuses that).
    """
    if chunk_overlap_tokens >= chunk_size_tokens:
        raise ValueError("chunk overlap must be smaller than the chunk size")
    splitter = _build_splitter(chunk_size_tokens, chunk_overlap_tokens)
    encode: Callable[[str], list[int]] = get_encoding().encode_ordinary
    chunks: list[Chunk] = []
    for page in pages:
        if not page.text.strip():
            continue
        for piece in splitter.split_text(page.text):
            text = piece.strip()
            if not text:
                continue
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    page_number=page.number,
                    text=text,
                    token_count=max(1, len(encode(text))),
                )
            )
    return chunks


def _build_splitter(size: int, overlap: int):  # noqa: ANN202 - llama_index is imported lazily
    from llama_index.core.node_parser import SentenceSplitter

    return SentenceSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        tokenizer=get_encoding().encode_ordinary,
        chunking_tokenizer_fn=split_sentences,
        include_metadata=False,
        include_prev_next_rel=False,
    )
