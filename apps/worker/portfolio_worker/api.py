from fastapi import FastAPI

app = FastAPI(
    title="Portfolio worker",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "portfolio-worker"}
