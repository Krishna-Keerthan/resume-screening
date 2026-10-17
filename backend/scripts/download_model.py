"""
Download the sentence-transformers model into the embedding cache at build time, so a
cold start does not fetch ~90 MB from Hugging Face. The one place the model is installed:
Render's buildCommand and the Dockerfile both run it, and nothing else knows the model
name or the cache path.

Run from backend/ after the dependencies are installed:

    python -m scripts.download_model

The cache path is the EMBEDDING_CACHE_DIR setting, which is absolute and defaults to
backend/.cache/embeddings, the path the running app reads. It must be inside backend/,
the only directory carried from the build to the running service on Render (and /app in
the image). After downloading, the script loads the model again from the cache with
local_files_only=True, exactly as the app does with EMBEDDING_OFFLINE=true, so a cache
that is incomplete fails the build instead of the first start.
"""
from pathlib import Path

from config.settings import BACKEND_DIR, BaseConfig


def main() -> None:
    from sentence_transformers import SentenceTransformer

    model = BaseConfig.EMBEDDING_MODEL
    cache = Path(BaseConfig.EMBEDDING_CACHE_DIR).resolve()
    if not cache.is_relative_to(BACKEND_DIR):
        raise SystemExit(
            f"EMBEDDING_CACHE_DIR {cache} is outside the project directory {BACKEND_DIR}. "
            "Only the project directory survives from the build to the running service, "
            "so a model downloaded there would be missing at runtime."
        )

    SentenceTransformer(model, cache_folder=str(cache))
    try:
        SentenceTransformer(model, cache_folder=str(cache), local_files_only=True).encode(["check"])
    except Exception as exc:
        raise SystemExit(
            f"The model {model} was downloaded but could not be loaded from {cache} offline: {exc}"
        ) from exc
    print(f"Embedding model {model} is in {cache} and loads offline")


if __name__ == "__main__":
    main()
