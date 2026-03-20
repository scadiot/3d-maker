"""TextureAtlas — wraps an image path and its associated atlas data."""

from __future__ import annotations

from typing import Any


class TextureAtlas:
    """Represents a texture atlas: an image file and its associated metadata."""

    def __init__(self, image_path: str, atlas_data: Any = None) -> None:
        self.image_path: str = image_path
        self.atlas_data: Any = atlas_data
