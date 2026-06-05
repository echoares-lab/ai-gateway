from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os

app = FastAPI()

# Scalar API Reference HTML
SCALAR_HTML = """
<!doctype html>
<html>
  <head>
    <title>API Reference</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi/translator.yaml"
    ></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""

@app.get("/")
async def get_docs():
    return HTMLResponse(SCALAR_HTML)

# Endpoint to serve OpenAPI YAMLs
@app.get("/openapi/{filename}")
async def get_openapi(filename: str):
    path = f"/app/docs/openapi/{filename}"
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return {"error": "Not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
