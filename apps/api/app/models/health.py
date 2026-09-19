from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["shipping-document-verification-api"] = "shipping-document-verification-api"
