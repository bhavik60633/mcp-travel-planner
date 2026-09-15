"""HTTP route: /api/images."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .service import ImageService

router = APIRouter()
_service: ImageService | None = None
_lock = threading.Lock()


def get_image_service() -> ImageService:
    global _service
    with _lock:
        if _service is None:
            _service = ImageService()
        return _service


@router.get("/api/images")
def images(query: str = "", service: ImageService = Depends(get_image_service)):
    text = " ".join(query.split())
    if not text:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "message": "A photo search needs some words, like a place name."})
    return service.photo(text)
