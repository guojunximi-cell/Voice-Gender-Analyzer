import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_DEV_PORT", "8080"))

    print(f"the backend will be run at http://127.0.0.1:{port}")
    uvicorn.run("backend:app", host="127.0.0.1", port=port)
