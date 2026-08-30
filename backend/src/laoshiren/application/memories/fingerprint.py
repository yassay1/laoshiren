"""Canonical content fingerprints for Memory forget suppression."""

from hashlib import sha256


def canonicalize_memory_content(content: str) -> str:
    return " ".join(content.strip().casefold().split())


def memory_content_fingerprint(content: str) -> str:
    canonical = canonicalize_memory_content(content)
    return sha256(canonical.encode()).hexdigest()
