import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="AI Gateway Admin UI (Docs Server)")

# Base directory for OpenAPI specs - adjust based on environment
OPENAPI_DIR = os.getenv("OPENAPI_DIR", "/app/docs/openapi")

def get_openapi_dir():
    if os.path.exists(OPENAPI_DIR):
        return OPENAPI_DIR
    # Local development fallbacks
    fallbacks = ["./docs/openapi", "../../docs/openapi", "docs/openapi"]
    for fb in fallbacks:
        if os.path.exists(fb):
            return fb
    return None

def get_scalar_html(spec_name: str):
    return f"""
<!doctype html>
<html>
  <head>
    <title>Admin UI - {spec_name}</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {{ margin: 0; padding: 0; }}
    </style>
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi/{spec_name}"
    ></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    directory = get_openapi_dir()
    if not directory:
        return f"<h1>Error</h1><p>OpenAPI directory not found. Tried: {OPENAPI_DIR} and several fallbacks.</p>"

    files = [f for f in os.listdir(directory) if f.endswith(".yaml") or f.endswith(".json")]
    files.sort()

    links = "".join([
        f'<li><a href="/docs/{f}" style="font-family: sans-serif; line-height: 2;">{f.replace(".yaml", "").replace(".json", "").replace("-", " ").title()}</a></li>'
        for f in files
    ])

    return f"""
<!doctype html>
<html>
  <head>
    <title>AI Gateway Admin UI</title>
    <style>
      body {{ font-family: sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; background: #f4f4f9; color: #333; }}
      h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
      ul {{ list-style: none; padding: 0; }}
      li {{ background: white; margin-bottom: 10px; padding: 10px 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); transition: transform 0.2s; }}
      li:hover {{ transform: translateX(10px); }}
      a {{ text-decoration: none; color: #3498db; font-weight: bold; display: block; }}
    </style>
  </head>
  <body>
    <h1>AI Gateway Admin UI - API Specifications</h1>
    <ul>{links}</ul>
  </body>
</html>
"""

@app.get("/docs/{spec_name}", response_class=HTMLResponse)
async def get_docs(spec_name: str):
    directory = get_openapi_dir()
    if not directory:
        raise HTTPException(status_code=500, detail="OpenAPI directory not found")

    path = os.path.join(directory, spec_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Specification not found")
    return HTMLResponse(get_scalar_html(spec_name))

@app.get("/openapi/{filename}")
async def get_openapi(filename: str):
    directory = get_openapi_dir()
    if not directory:
        raise HTTPException(status_code=500, detail="OpenAPI directory not found")

    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(path, "r") as f:
        content = f.read()
        media_type = "application/json" if filename.endswith(".json") else "text/yaml"
        return HTMLResponse(content=content, media_type=media_type)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
