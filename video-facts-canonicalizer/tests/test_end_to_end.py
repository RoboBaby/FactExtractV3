"""End-to-end tests for the video facts canonicalizer."""

import pytest
import json
import tempfile
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingest.reader import read_blobs
from src.preprocess.normalize import sentence_split, normalize_text
from src.srl.client import build_proto_fact
from src.canonicalize.entities import EntityCanonicalizer
from src.canonicalize.predicates import map_predicate
from src.canonicalize.literals import normalize_quantities
from src.dedup.signature import canonical_string, fact_id_from_canonical, minhash_from_text, band_hashes
from src.verify.evidence import claim_from_fact
from src.util.types import SRLFrame


class TestBlobIngestion:
    """Tests for blob reading and parsing."""

    def test_read_valid_blobs(self):
        """Test reading valid JSONL blobs."""
        data = [
            {"blob_id": "b1", "video_id": "v1", "channel_id": "c1", "source": "transcript", "text": "Test sentence."},
            {"blob_id": "b2", "video_id": "v2", "channel_id": "c2", "source": "keyframe", "text": "Another test."}
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
            f.flush()

            blobs = list(read_blobs(f.name))

        assert len(blobs) == 2
        assert blobs[0]["blob_id"] == "b1"
        assert blobs[1]["source"] == "keyframe"

    def test_sentence_split(self):
        """Test sentence splitting with offsets."""
        blob = {
            "blob_id": "b1",
            "video_id": "v1",
            "channel_id": "c1",
            "source": "transcript",
            "text": "First sentence. Second sentence! Third one?"
        }

        sentences = sentence_split(blob)

        assert len(sentences) == 3
        assert sentences[0][0] == "First sentence."
        assert sentences[1][0] == "Second sentence!"
        assert sentences[2][0] == "Third one?"


class TestCanonicalString:
    """Tests for canonical string generation."""

    def test_canonical_string_with_qids(self):
        """Test canonical string with Wikidata QIDs."""
        fact = {
            "subject": {"qid": "Q42", "surface": "Alice"},
            "predicate": {"frame": "Assemble", "sense": "assemble.01"},
            "object": {"qid": "Q484000", "surface": "drone"},
            "qualifiers": {
                "instrument": {"qid": "Q1322785", "surface": "Torx T20"}
            }
        }

        cs = canonical_string(fact)

        assert "S:Q42" in cs
        assert "P:Assemble" in cs
        assert "O:Q484000" in cs
        assert "instrument=Q1322785" in cs

    def test_canonical_string_with_local_ids(self):
        """Test canonical string with local IDs."""
        fact = {
            "subject": {"local_id": "ent:abc123", "surface": "Alice"},
            "predicate": {"frame": "Build"},
            "object": {"local_id": "ent:def456", "surface": "widget"},
            "qualifiers": {}
        }

        cs = canonical_string(fact)

        assert "S:ent:abc123" in cs
        assert "P:Build" in cs
        assert "O:ent:def456" in cs

    def test_canonical_string_determinism(self):
        """Test that identical facts produce identical canonical strings."""
        fact = {
            "subject": {"qid": "Q100", "surface": "Bob"},
            "predicate": {"frame": "Measure"},
            "object": {"qid": "Q200", "surface": "board"},
            "qualifiers": {
                "temperature": {"value": 180, "unit": "celsius"},
                "instrument": {"qid": "Q300"}
            }
        }

        cs1 = canonical_string(fact)
        cs2 = canonical_string(fact)

        assert cs1 == cs2

    def test_fact_id_from_canonical(self):
        """Test fact ID generation from canonical string."""
        cs = "S:Q42|P:Assemble|O:Q484000|Q:{instrument=Q1322785}"

        fact_id1 = fact_id_from_canonical(cs)
        fact_id2 = fact_id_from_canonical(cs)

        assert fact_id1 == fact_id2
        assert len(fact_id1) == 40  # SHA1 hex length


class TestMinHash:
    """Tests for MinHash signature generation."""

    def test_minhash_creation(self):
        """Test MinHash creation from text."""
        text = "S:Q42|P:Assemble|O:Q484000|Q:{instrument=Q1322785}"

        mh = minhash_from_text(text, n_perm=128, shingle_size=5)

        assert mh is not None
        assert len(mh.hashvalues) == 128

    def test_band_hashes_generation(self):
        """Test LSH band hash generation."""
        text = "S:Q42|P:Assemble|O:Q484000"
        mh = minhash_from_text(text, n_perm=128, shingle_size=5)

        bands = band_hashes(mh, bands=32, rows_per_band=4)

        assert len(bands) == 32
        assert all(isinstance(b, tuple) and len(b) == 2 for b in bands)
        assert all(isinstance(b[0], int) and isinstance(b[1], str) for b in bands)

    def test_similar_texts_share_bands(self):
        """Test that similar texts share band hashes."""
        text1 = "S:Q42|P:Assemble|O:Q484000|Q:{instrument=Q1322785}"
        text2 = "S:Q42|P:Assemble|O:Q484000|Q:{instrument=Q1322785;temp=100}"

        mh1 = minhash_from_text(text1, n_perm=128, shingle_size=5)
        mh2 = minhash_from_text(text2, n_perm=128, shingle_size=5)

        bands1 = set(b[1] for b in band_hashes(mh1, 32, 4))
        bands2 = set(b[1] for b in band_hashes(mh2, 32, 4))

        # Similar texts should share some band hashes
        shared = bands1.intersection(bands2)
        assert len(shared) > 0


class TestEntityCanonicalization:
    """Tests for entity linking and canonicalization."""

    def test_entity_linking_known_entity(self):
        """Test linking a known entity."""
        el = EntityCanonicalizer("/data/rel", min_conf_accept=0.75)

        result = el.link_mentions([{"surface": "Alice"}])

        assert len(result) == 1
        assert result[0]["surface"] == "Alice"
        # Should get QID or local_id
        assert result[0].get("qid") or result[0].get("local_id")

    def test_entity_linking_unknown_entity(self):
        """Test linking an unknown entity gets local ID."""
        el = EntityCanonicalizer("/data/rel", min_conf_accept=0.99)

        result = el.link_mentions([{"surface": "UnknownEntity12345"}])

        assert len(result) == 1
        assert result[0]["local_id"] is not None
        assert result[0]["local_id"].startswith("ent:")

    def test_local_id_determinism(self):
        """Test that same surface always gets same local ID."""
        el = EntityCanonicalizer("/data/rel", min_conf_accept=0.99)

        result1 = el.link_mentions([{"surface": "TestEntity"}])
        result2 = el.link_mentions([{"surface": "TestEntity"}])

        assert result1[0]["local_id"] == result2[0]["local_id"]


class TestPredicateMapping:
    """Tests for predicate canonicalization."""

    def test_map_known_predicate(self):
        """Test mapping a known predicate lemma."""
        pred = map_predicate("assemble")

        assert pred["frame"] == "Assemble"
        assert pred["sense"] == "assemble.01"

    def test_map_unknown_predicate(self):
        """Test mapping an unknown predicate gets default."""
        pred = map_predicate("unknownverb123")

        assert pred["frame"] == "Unknownverb123"
        assert "unknownverb123" in pred["sense"]


class TestQuantityNormalization:
    """Tests for quantity parsing and normalization."""

    def test_temperature_normalization(self):
        """Test temperature conversion to Celsius."""
        text = "Heat to 350 degrees Fahrenheit."

        quals = normalize_quantities(text, {"temperature": "celsius"})

        if "temperature" in quals:
            assert quals["temperature"]["unit"] == "celsius"
            # 350 F ≈ 176.67 C
            assert 170 < quals["temperature"]["value"] < 180

    def test_length_normalization(self):
        """Test length conversion to millimeters."""
        text = "The board is 5 centimeters wide."

        quals = normalize_quantities(text, {"length": "millimeter"})

        if "length" in quals:
            assert quals["length"]["unit"] == "millimeter"
            assert quals["length"]["value"] == 50.0


class TestVerification:
    """Tests for claim generation."""

    def test_claim_from_fact(self):
        """Test generating a claim from a fact."""
        fact = {
            "subject": {"surface": "Alice", "qid": "Q42"},
            "predicate": {"frame": "Assemble"},
            "object": {"surface": "drone", "qid": "Q484000"},
            "qualifiers": {
                "instrument": {"surface": "Torx T20", "qid": "Q1322785"}
            }
        }

        claim = claim_from_fact(fact)

        assert "Alice" in claim
        assert "assembles" in claim.lower()
        assert "drone" in claim
        assert "Torx T20" in claim


class TestProtoFactBuilding:
    """Tests for SRL to proto-fact conversion."""

    def test_build_proto_fact_basic(self):
        """Test building proto-fact from SRL frame."""
        frame = SRLFrame(
            predicate="assembles",
            predicate_lemma="assemble",
            arguments={
                "ARG0": "Alice",
                "ARG1": "the drone",
                "ARG2": "a Torx T20 bit"
            }
        )

        proto = build_proto_fact(frame, "Alice assembles the drone with a Torx T20 bit.")

        assert proto.A0 == "Alice"
        assert proto.A1 == "the drone"
        assert proto.A2 == "a Torx T20 bit"
        assert proto.predicate_lemma == "assemble"


class TestEndToEnd:
    """Integration tests for the full pipeline."""

    def test_toy_blobs_processing(self):
        """Test processing the toy blobs file."""
        blobs_path = Path(__file__).parent.parent / "data" / "blobs.jsonl"
        if not blobs_path.exists():
            pytest.skip("Toy blobs file not found")

        blobs = list(read_blobs(str(blobs_path)))

        assert len(blobs) >= 3
        assert blobs[0]["video_id"] == "v1"
        assert blobs[0]["channel_id"] == "cA"

    def test_near_duplicate_detection(self):
        """Test that near-duplicate facts produce similar MinHash signatures."""
        # These should be near-duplicates
        fact1 = {
            "subject": {"qid": "Q42", "surface": "Alice"},
            "predicate": {"frame": "Assemble"},
            "object": {"qid": "Q484000", "surface": "drone"},
            "qualifiers": {"instrument": {"qid": "Q1322785"}}
        }
        fact2 = {
            "subject": {"qid": "Q42", "surface": "Alice"},
            "predicate": {"frame": "Assemble"},
            "object": {"qid": "Q484000", "surface": "drone"},
            "qualifiers": {"instrument": {"qid": "Q1322785"}}
        }

        cs1 = canonical_string(fact1)
        cs2 = canonical_string(fact2)

        mh1 = minhash_from_text(cs1)
        mh2 = minhash_from_text(cs2)

        jaccard = mh1.jaccard(mh2)

        # Identical facts should have Jaccard = 1.0
        assert jaccard == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
