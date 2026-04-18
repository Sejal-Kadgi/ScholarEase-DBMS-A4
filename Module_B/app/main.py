from fastapi import FastAPI
from app.routes import auth_routes, member_routes, scholarship_routes, payment_routes
from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(member_routes.router)
app.include_router(scholarship_routes.router)
app.include_router(payment_routes.router)

# Serve static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/templates", StaticFiles(directory="templates"), name="templates")

@app.get("/")
def home():
    return {"message": "ScholarEase API running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)