"""Test data generator using Anthropic LLM."""

import os
import json
import uuid
import random
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

import anthropic

from src.util.logging import get_logger

logger = get_logger("data_generator")


class TestDataGenerator:
    """
    Generate synthetic test data using Anthropic's Claude API.

    Creates realistic video narrative blobs for testing the
    facts canonicalizer pipeline.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        prompts_dir: str = "src/data_generator/prompts",
        output_dir: str = "resources/generated_data"
    ):
        """
        Initialize the test data generator.

        Args:
            api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var)
            model: Model to use for generation
            prompts_dir: Directory containing prompt templates
            output_dir: Directory for generated data
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.prompts_dir = Path(prompts_dir)
        self.output_dir = Path(output_dir)

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_prompt(self, prompt_name: str) -> str:
        """
        Load a prompt template from file.

        Args:
            prompt_name: Name of prompt file (without extension)

        Returns:
            Prompt template string
        """
        prompt_path = self.prompts_dir / f"{prompt_name}.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def generate_narrative(
        self,
        topic: Optional[str] = None,
        duration_seconds: int = 60,
        style: str = "instructional",
        prompt_name: str = "narrative_prompt"
    ) -> Dict[str, Any]:
        """
        Generate a single narrative blob.

        Args:
            topic: Specific topic (e.g., "drone assembly", "soldering")
            duration_seconds: Approximate duration the narrative covers
            style: Style of content (instructional, documentary, tutorial)
            prompt_name: Name of prompt template to use

        Returns:
            Generated blob dictionary
        """
        # Load and format prompt
        prompt_template = self.load_prompt(prompt_name)

        # Select random topic if not specified
        if topic is None:
            topic = random.choice(self._get_default_topics())

        prompt = prompt_template.format(
            topic=topic,
            duration_seconds=duration_seconds,
            style=style
        )

        logger.info(f"Generating narrative for topic: {topic}")

        # Call Anthropic API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract generated text
        generated_text = response.content[0].text

        # Parse the response (expecting JSON)
        try:
            # Try to extract JSON from response
            if "```json" in generated_text:
                json_str = generated_text.split("```json")[1].split("```")[0]
            elif "```" in generated_text:
                json_str = generated_text.split("```")[1].split("```")[0]
            else:
                json_str = generated_text

            blob_data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            # If not valid JSON, wrap the text
            blob_data = {
                "text": generated_text,
                "topic": topic,
                "duration_seconds": duration_seconds
            }

        # Ensure required fields
        blob = self._create_blob(blob_data, topic, duration_seconds)

        return blob

    def _create_blob(
        self,
        data: Dict[str, Any],
        topic: str,
        duration_seconds: int
    ) -> Dict[str, Any]:
        """
        Create a properly formatted blob from generated data.

        Args:
            data: Raw generated data
            topic: Topic of the narrative
            duration_seconds: Duration covered

        Returns:
            Formatted blob dictionary
        """
        blob_id = str(uuid.uuid4())
        video_id = f"vid_{uuid.uuid4().hex[:8]}"
        channel_id = f"ch_{random.choice(['maker', 'tech', 'diy', 'repair', 'build'])}"

        # Calculate timestamps
        t_start = random.uniform(0, 300)  # Random start in first 5 minutes
        t_end = t_start + duration_seconds

        return {
            "blob_id": blob_id,
            "video_id": video_id,
            "channel_id": channel_id,
            "source": "narrative",
            "text": data.get("text", data.get("narrative", str(data))),
            "t_start": round(t_start, 2),
            "t_end": round(t_end, 2),
            "frames": None,
            "metadata": {
                "topic": topic,
                "duration_seconds": duration_seconds,
                "generated_at": datetime.utcnow().isoformat(),
                "model": self.model
            }
        }

    def generate_batch(
        self,
        count: int,
        topics: Optional[List[str]] = None,
        prompt_name: str = "narrative_prompt",
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple narrative blobs.

        Args:
            count: Number of blobs to generate
            topics: List of topics to cycle through
            prompt_name: Name of prompt template to use
            **kwargs: Additional arguments for generate_narrative

        Returns:
            List of generated blobs
        """
        if topics is None:
            topics = self._get_default_topics()

        blobs = []
        for i in range(count):
            topic = topics[i % len(topics)]
            try:
                blob = self.generate_narrative(topic=topic, prompt_name=prompt_name, **kwargs)
                blobs.append(blob)
                logger.info(f"Generated blob {i+1}/{count}")
            except Exception as e:
                logger.error(f"Failed to generate blob {i+1}: {e}")

        return blobs

    def save_single_blob(
        self,
        blob: Dict[str, Any],
        resource_id: Optional[int] = None
    ) -> Path:
        """
        Save a single blob to its own numbered resource directory.

        Args:
            blob: Single blob dictionary
            resource_id: Specific resource ID (auto-increments if None)

        Returns:
            Path to the saved resource directory
        """
        if resource_id is None:
            resource_id = self._get_next_resource_id()

        # Create resource directory
        resource_dir = self.output_dir / f"{resource_id:04d}"
        resource_dir.mkdir(parents=True, exist_ok=True)

        # Save blob as JSONL (single blob per file)
        blobs_path = resource_dir / "blobs.jsonl"
        with open(blobs_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(blob) + "\n")

        # Save metadata
        metadata = {
            "resource_id": resource_id,
            "blob_count": 1,
            "generated_at": datetime.utcnow().isoformat(),
            "model": self.model,
            "topic": blob.get("metadata", {}).get("topic", "unknown")
        }
        metadata_path = resource_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved blob to {resource_dir}")
        return resource_dir

    def save_to_resource(
        self,
        blobs: List[Dict[str, Any]],
        resource_id: Optional[int] = None
    ) -> Path:
        """
        Save generated blobs to a numbered resource directory.

        Args:
            blobs: List of blob dictionaries
            resource_id: Specific resource ID (auto-increments if None)

        Returns:
            Path to the saved resource directory
        """
        if resource_id is None:
            resource_id = self._get_next_resource_id()

        # Create resource directory
        resource_dir = self.output_dir / f"{resource_id:04d}"
        resource_dir.mkdir(parents=True, exist_ok=True)

        # Save blobs as JSONL
        blobs_path = resource_dir / "blobs.jsonl"
        with open(blobs_path, "w", encoding="utf-8") as f:
            for blob in blobs:
                f.write(json.dumps(blob) + "\n")

        # Save metadata
        metadata = {
            "resource_id": resource_id,
            "blob_count": len(blobs),
            "generated_at": datetime.utcnow().isoformat(),
            "model": self.model,
            "topics": list(set(b.get("metadata", {}).get("topic", "unknown") for b in blobs))
        }
        metadata_path = resource_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved {len(blobs)} blobs to {resource_dir}")
        return resource_dir

    def _get_next_resource_id(self) -> int:
        """Get the next available resource ID."""
        existing = [
            int(d.name) for d in self.output_dir.iterdir()
            if d.is_dir() and d.name.isdigit()
        ]
        return max(existing, default=0) + 1

    def _get_default_topics(self) -> List[str]:
        """Get default list of topics for generation."""
        return [
            "drone assembly and calibration",
            "soldering electronic components",
            "3D printer maintenance and troubleshooting",
            "Arduino sensor project setup",
            "mechanical keyboard building",
            "CNC router operation",
            "laser cutter safety and operation",
            "PCB etching process",
            "servo motor installation",
            "battery pack assembly",
            "multimeter usage for diagnostics",
            "heat shrink tubing application",
            "wire crimping and termination",
            "oscilloscope signal analysis",
            "power supply modification",
            "LED strip installation",
            "motor driver configuration",
            "GPS module integration",
            "camera gimbal assembly",
            "radio transmitter binding"
        ]


def get_generator(**kwargs) -> TestDataGenerator:
    """
    Factory function to create a TestDataGenerator.

    Args:
        **kwargs: Arguments for TestDataGenerator

    Returns:
        Configured TestDataGenerator instance
    """
    return TestDataGenerator(**kwargs)
