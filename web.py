from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "online"}

@app.get("/badge")
def badge():
    return JSONResponse({
        "schemaVersion": 1,
        "label": "Status",
        "message": "Online",
        "color": "green"
    })
