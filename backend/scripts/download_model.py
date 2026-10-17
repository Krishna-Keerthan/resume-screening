"""
Download the sentence-transformers model into the embedding cache at build time, so a
cold start does not fetch ~90 MB from Hugging Face.

Run from backend/ after the dependencies are installed (Render's buildCommand, the
Dockerfile). It uses the same settings and the same call as EmbeddingService, so the
cache it fills is the one the app reads:

    python -m scripts.download_model
"""
from config.settings import BaseConfig


def main() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(BaseConfig.EMBEDDING_MODEL, cache_folder=BaseConfig.EMBEDDING_CACHE_DIR)
    print(f"Embedding model {BaseConfig.EMBEDDING_MODEL} is in {BaseConfig.EMBEDDING_CACHE_DIR}")


if __name__ == "__main__":
    main()
