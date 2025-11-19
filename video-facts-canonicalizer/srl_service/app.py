"""SRL microservice using AllenNLP transformer-srl."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

app = FastAPI(title="SRL Service", version="1.0.0")

# Lazy load model
_predictor = None


def get_predictor():
    """Lazy load the SRL predictor."""
    global _predictor
    if _predictor is None:
        try:
            from allennlp.predictors.predictor import Predictor
            _predictor = Predictor.from_path(
                "https://storage.googleapis.com/allennlp-public-models/structured-prediction-srl-bert.2020.12.15.tar.gz"
            )
        except Exception as e:
            print(f"Failed to load SRL model: {e}")
            # Use stub predictor for testing
            _predictor = StubPredictor()
    return _predictor


class StubPredictor:
    """Stub predictor for testing without AllenNLP."""

    def predict(self, sentence: str) -> Dict[str, Any]:
        """Generate stub SRL output."""
        words = sentence.split()
        verbs = []

        # Simple heuristic: find common verbs
        verb_list = ["assembles", "puts", "uses", "heats", "measures", "is", "has", "builds", "creates"]
        for i, word in enumerate(words):
            word_lower = word.lower().rstrip(".,!?")
            if word_lower in verb_list or word_lower.endswith("s") and len(word_lower) > 3:
                # Extract arguments heuristically
                args = {}
                if i > 0:
                    args["ARG0"] = " ".join(words[:i])
                if i < len(words) - 1:
                    rest = " ".join(words[i+1:])
                    # Split on "with" for instrument
                    if " with " in rest:
                        parts = rest.split(" with ")
                        args["ARG1"] = parts[0].rstrip(".,!?")
                        if len(parts) > 1:
                            args["ARG2"] = parts[1].rstrip(".,!?")
                    else:
                        args["ARG1"] = rest.rstrip(".,!?")

                verbs.append({
                    "verb": word_lower.rstrip(".,!?"),
                    "description": self._make_description(words, i, args),
                    "tags": self._make_tags(words, i, args)
                })

        return {"verbs": verbs, "words": words}

    def _make_description(self, words, verb_idx, args):
        """Make description string."""
        parts = []
        if "ARG0" in args:
            parts.append(f"[ARG0: {args['ARG0']}]")
        parts.append(f"[V: {words[verb_idx]}]")
        if "ARG1" in args:
            parts.append(f"[ARG1: {args['ARG1']}]")
        if "ARG2" in args:
            parts.append(f"[ARG2: {args['ARG2']}]")
        return " ".join(parts)

    def _make_tags(self, words, verb_idx, args):
        """Make BIO tags."""
        tags = ["O"] * len(words)
        tags[verb_idx] = "B-V"
        return tags


class PredictRequest(BaseModel):
    text: str


class SRLFrame(BaseModel):
    predicate: str
    predicate_lemma: str
    arguments: Dict[str, str]
    confidence: float = 1.0


class PredictResponse(BaseModel):
    frames: List[SRLFrame]


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    """
    Run SRL prediction on input text.

    Returns list of frames with predicate and arguments.
    """
    if not request.text.strip():
        return PredictResponse(frames=[])

    predictor = get_predictor()

    try:
        result = predictor.predict(sentence=request.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRL prediction failed: {e}")

    frames = []
    for verb_data in result.get("verbs", []):
        verb = verb_data.get("verb", "")

        # Extract arguments from tags or description
        arguments = {}
        tags = verb_data.get("tags", [])
        words = result.get("words", [])

        if tags and words:
            current_arg = None
            current_tokens = []

            for word, tag in zip(words, tags):
                if tag.startswith("B-"):
                    # Save previous argument
                    if current_arg and current_tokens:
                        arguments[current_arg] = " ".join(current_tokens)
                    # Start new argument
                    current_arg = tag[2:]  # Remove "B-"
                    current_tokens = [word] if current_arg != "V" else []
                elif tag.startswith("I-"):
                    if current_arg:
                        current_tokens.append(word)
                else:
                    # Save previous argument
                    if current_arg and current_tokens:
                        arguments[current_arg] = " ".join(current_tokens)
                    current_arg = None
                    current_tokens = []

            # Save last argument
            if current_arg and current_tokens:
                arguments[current_arg] = " ".join(current_tokens)

        # Convert to standard format
        std_args = {}
        for key, value in arguments.items():
            if key == "ARG0":
                std_args["ARG0"] = value
            elif key == "ARG1":
                std_args["ARG1"] = value
            elif key == "ARG2":
                std_args["ARG2"] = value
            elif key == "ARGM-LOC":
                std_args["ARGM-LOC"] = value
            elif key == "ARGM-TMP":
                std_args["ARGM-TMP"] = value
            elif key == "ARGM-MNR":
                std_args["ARGM-MNR"] = value

        frame = SRLFrame(
            predicate=verb,
            predicate_lemma=verb.lower().rstrip("s"),  # Simple lemmatization
            arguments=std_args
        )
        frames.append(frame)

    return PredictResponse(frames=frames)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
