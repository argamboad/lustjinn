"""The FastAPI application: the object uvicorn serves."""

from fastapi import FastAPI

app = FastAPI(title="Lustjinn")


@app.get("/health")
async def health() -> dict[str, str]:
    """Answers while the process is up. Render and the PWA's waking screen poll it."""
    return {"status": "ok"}
