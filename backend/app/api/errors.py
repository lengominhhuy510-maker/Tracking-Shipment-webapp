"""REST error envelope helper (IC§3.1 / IC§11): {"detail": {"code", "message"}}."""

from typing import NoReturn

from fastapi import HTTPException


def raise_api_error(status: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code, "message": message})
