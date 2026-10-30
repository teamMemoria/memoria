from fastapi import FastAPI

app = FastAPI(title="Call Assist")


@app.get("/health")
def health():
    return {"status": "ok"}
