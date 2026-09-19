from fastapi import FastAPI

from app.models.health import HealthResponse

app = FastAPI(
    title="Shipping Document Verification API",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()
