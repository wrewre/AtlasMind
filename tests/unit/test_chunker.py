"""
Unit tests for the chunking service's text splitter.
Run with: pytest tests/unit/test_chunker.py -v
"""
import sys
sys.path.insert(0, "services/chunking_service")

from main import split_into_chunks


def make_text(sentences: int, chars_each: int = 80) -> str:
    """Generate synthetic text with a given number of sentences."""
    sentence = "This is a test sentence covering an important topic in the document. "
    return (sentence[:chars_each] + " ") * sentences


class TestChunker:

    def test_short_text_single_chunk(self):
        text = "This is a short document. It has only two sentences."
        chunks = split_into_chunks(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0][0] == text.strip()

    def test_chunk_count_reasonable(self):
        # 3000 chars with chunk_size=1500 → approx 2 chunks
        text = make_text(40, 75)  # ~3000 chars
        chunks = split_into_chunks(text, chunk_size=1500, overlap=200)
        assert 2 <= len(chunks) <= 4

    def test_chunks_cover_text(self):
        """All significant text should appear in at least one chunk."""
        text = "Alpha sentence here. Beta sentence there. Gamma sentence everywhere. Delta sentence anywhere."
        chunks = split_into_chunks(text, chunk_size=200, overlap=50)
        combined = " ".join(c for c, _, _ in chunks).lower()
        for keyword in ["alpha", "beta", "gamma", "delta"]:
            assert keyword in combined, f"Keyword '{keyword}' not found in any chunk"

    def test_overlap_means_repeated_content(self):
        """With overlap, some content should appear in consecutive chunks."""
        text = make_text(30, 80)  # ~2400 chars
        chunks = split_into_chunks(text, chunk_size=600, overlap=200)
        if len(chunks) >= 2:
            # The end of chunk 0 should share words with start of chunk 1
            end_of_first = set(chunks[0][0].split()[-20:])
            start_of_second = set(chunks[1][0].split()[:20])
            assert len(end_of_first & start_of_second) > 0

    def test_char_positions_monotonic(self):
        """char_start should be non-decreasing across chunks."""
        text = make_text(50, 80)
        chunks = split_into_chunks(text, chunk_size=800, overlap=150)
        starts = [c[1] for c in chunks]
        assert starts == sorted(starts)

    def test_empty_text(self):
        assert split_into_chunks("") == []

    def test_whitespace_only(self):
        assert split_into_chunks("   \n\t  ") == []

    def test_min_chunk_size_filters_tiny_tails(self):
        """Last chunk smaller than MIN_CHUNK_SIZE should be dropped."""
        text = make_text(10, 80) + " Ab."  # tiny tail
        chunks = split_into_chunks(text, chunk_size=600, overlap=100)
        for text_chunk, _, _ in chunks:
            assert len(text_chunk) >= 100  # MIN_CHUNK_SIZE default

    def test_single_long_sentence(self):
        """A single very long sentence should produce one chunk."""
        text = "word " * 500  # no sentence terminators
        chunks = split_into_chunks(text, chunk_size=1000, overlap=100)
        assert len(chunks) >= 1
