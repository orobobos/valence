#!/usr/bin/env python3
"""Download embedding model for offline use.

This script pre-downloads the embedding model so Valence can run
in air-gapped environments without network access.

Examples:
    # Download to default HuggingFace cache
    python scripts/download_model.py

    # Save to custom path for portable deployment
    python scripts/download_model.py --save-path /opt/valence/models/bge-small-en-v1.5
    
    # Use a different model
    python scripts/download_model.py --model sentence-transformers/all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def download_model(model_name: str, save_path: str | None = None) -> None:
    """Download embedding model for offline use.
    
    Args:
        model_name: HuggingFace model name to download
        save_path: Optional custom path to save the model
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Error: sentence-transformers not installed.", file=sys.stderr)
        print("Install with: pip install sentence-transformers", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading {model_name}...")
    print("This may take a moment on first run.")
    print()

    try:
        model = SentenceTransformer(model_name)
    except Exception as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        sys.exit(1)

    dim = model.get_sentence_embedding_dimension()
    print(f"Model loaded successfully ({dim} dimensions)")

    if save_path:
        save_dir = Path(save_path)
        print(f"Saving to {save_dir}...")
        save_dir.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(save_dir))
        print()
        print("=" * 60)
        print("Model saved for offline use!")
        print()
        print("On your target machine, set:")
        print(f"  export VALENCE_EMBEDDING_MODEL_PATH={save_dir}")
        print("=" * 60)
    else:
        # Model is now in HuggingFace cache
        cache_path = (
            Path.home()
            / ".cache"
            / "huggingface"
            / "hub"
            / f"models--{model_name.replace('/', '--')}"
        )
        print()
        print("=" * 60)
        print("Model downloaded to HuggingFace cache!")
        print()
        print(f"Cache location: {cache_path}")
        print()
        print("To deploy to an air-gapped machine:")
        print(f"  scp -r {cache_path} user@target:~/.cache/huggingface/hub/")
        print()
        print("Or re-run with --save-path to save to a custom location.")
        print("=" * 60)

    print()
    print("Done!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download embedding model for offline use",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    Download to default cache
  %(prog)s --save-path /opt/valence/models    Save to custom path
  %(prog)s --model all-MiniLM-L6-v2           Use different model
        """,
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="Model name to download (default: BAAI/bge-small-en-v1.5)",
    )
    parser.add_argument(
        "--save-path",
        help="Custom path to save the model for portable offline use",
    )

    args = parser.parse_args()
    download_model(args.model, args.save_path)


if __name__ == "__main__":
    main()
