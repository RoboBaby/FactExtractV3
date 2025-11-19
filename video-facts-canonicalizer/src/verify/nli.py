"""NLI-based verification (FEVER/FActScore style)."""

from typing import List, Optional

from src.util.logging import get_logger

logger = get_logger("verify.nli")

# Lazy loading of heavy models
_retriever = None
_nli_model = None
_nli_tokenizer = None


class LocalVerifier:
    """
    Local verification using retrieval + NLI.

    Uses sentence embeddings to retrieve relevant evidence,
    then NLI to score support for the claim.
    """

    def __init__(
        self,
        retriever_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        nli_model: str = "roberta-large-mnli",
        min_support: float = 0.6
    ):
        """
        Initialize the local verifier.

        Args:
            retriever_model: Sentence transformer model for retrieval
            nli_model: NLI model for entailment scoring
            min_support: Minimum support score threshold
        """
        self.retriever_model_name = retriever_model
        self.nli_model_name = nli_model
        self.min_support = min_support

        self._retr = None
        self._tok = None
        self._nli = None
        self._initialized = False

    def _initialize(self):
        """Lazy initialization of models."""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._retr = SentenceTransformer(self.retriever_model_name)
            logger.info(f"Loaded retriever model: {self.retriever_model_name}")
        except Exception as e:
            logger.error(f"Failed to load retriever model: {e}")
            self._retr = None

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self._tok = AutoTokenizer.from_pretrained(self.nli_model_name)
            self._nli = AutoModelForSequenceClassification.from_pretrained(self.nli_model_name)
            logger.info(f"Loaded NLI model: {self.nli_model_name}")
        except Exception as e:
            logger.error(f"Failed to load NLI model: {e}")
            self._tok = None
            self._nli = None

        self._initialized = True

    def score(self, claim: str, evidence_sentences: List[str]) -> float:
        """
        Score support for a claim given evidence sentences.

        Args:
            claim: The claim to verify
            evidence_sentences: List of potential evidence sentences

        Returns:
            Support score between 0 and 1
        """
        if not evidence_sentences:
            return 0.0

        self._initialize()

        if self._retr is None or self._nli is None:
            # Return neutral score if models not available
            logger.warning("Verification models not available, returning default score")
            return 0.5

        try:
            import torch
            from sentence_transformers import util

            # Encode claim and evidence
            claim_emb = self._retr.encode([claim], normalize_embeddings=True)
            ev_emb = self._retr.encode(evidence_sentences, normalize_embeddings=True)

            # Get cosine similarities
            cos = util.cos_sim(claim_emb, ev_emb)[0].tolist()

            # Select top-k most similar sentences
            top_k = min(3, len(evidence_sentences))
            top_idxs = sorted(range(len(cos)), key=lambda i: -cos[i])[:top_k]
            top_sents = [evidence_sentences[i] for i in top_idxs]

            # Run NLI on top sentences
            scores = []
            for sent in top_sents:
                inputs = self._tok(
                    claim, sent,
                    return_tensors="pt",
                    truncation=True,
                    max_length=512
                )
                with torch.no_grad():
                    logits = self._nli(**inputs).logits[0]

                # Label order for roberta-large-mnli: contradiction, neutral, entailment
                probs = torch.softmax(logits, dim=-1)
                entailment_prob = probs[2].item()
                scores.append(entailment_prob)

            # Return maximum entailment score
            return max(scores) if scores else 0.0

        except Exception as e:
            logger.error(f"Verification scoring failed: {e}")
            return 0.0

    def batch_score(
        self,
        claims: List[str],
        evidence_lists: List[List[str]]
    ) -> List[float]:
        """
        Score multiple claims in batch.

        Args:
            claims: List of claims
            evidence_lists: List of evidence sentence lists

        Returns:
            List of support scores
        """
        return [
            self.score(claim, evidence)
            for claim, evidence in zip(claims, evidence_lists)
        ]
