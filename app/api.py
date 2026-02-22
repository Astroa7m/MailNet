import os
import datetime

import uvicorn
from authlib.integrations.starlette_client import OAuth
from chainlit.utils import mount_chainlit
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()
app = FastAPI()
CHAINLIT_URL = os.getenv("CHAINLIT_URL")
JWT_SECRET = os.getenv("JWT_SECRET")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


class ChainlitAuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/chat/login"):
            return await call_next(request)

        # check if user is authenticated
        user = request.session.get("user")
        if not user:
            # Not authenticated - redirect to login
            print("MIDDLEWARE] No user in session, redirecting to login")
            return RedirectResponse(url="/", status_code=303)

        # user is authenticated then continue
        response = await call_next(request)
        return response


app.add_middleware(ChainlitAuthMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET"),
    https_only=False,  # todo fix later
    same_site="lax"
)

# for HTML template serving
templates = Jinja2Templates(directory="templates")

oauth = OAuth()

oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": " ".join([
            "openid",
            "email",
            "profile",
            "https://mail.google.com/",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.modify",
        ]),
        "access_type": "offline",  # so we can have a refresh token for off-site use
        "prompt": "consent"  # makes google return refresh token
    },
)

oauth.register(
    name="microsoft",
    client_id=os.getenv("AZURE_APPLICATION_CLIENT_ID"),
    client_secret=os.getenv("AZURE_SECRET_VALUE"),
    server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    client_kwargs={
        "scope": " ".join([
            "openid",
            "email",
            "profile",
            "offline_access",  # microsoft's equivalent of access_type=offline
            "https://graph.microsoft.com/Mail.ReadWrite",
            "https://graph.microsoft.com/Mail.Send",
            "https://graph.microsoft.com/MailboxSettings.ReadWrite",
            "https://graph.microsoft.com/User.Read",
        ]),
    }
)

mount_chainlit(app=app, target="chatting_ui.py", path="/chat")


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/chat")
    return templates.TemplateResponse("login.html", {"request": request})


# Google

@app.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google", name="auth_google")
async def auth_google(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")

    request.session["user"] = {
        "email": user_info["email"],
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "provider": "google",
    }
    print("got token", token)
    # for mcp format
    google_token_json = {
        "token": token["access_token"],
        "refresh_token": token.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "scopes": token["scope"].split(" "),
        "expiry": datetime.datetime.fromtimestamp(token["expires_at"], datetime.UTC).isoformat() + "Z"
    }

    request.session['google_token'] = google_token_json
    return RedirectResponse(url="/chat")


# Microsoft

@app.get("/login/microsoft")
async def login_microsoft(request: Request):
    redirect_uri = request.url_for("auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@app.get("/auth/microsoft", name="auth_microsoft")
async def auth_microsoft(request: Request):
    token = await oauth.microsoft.authorize_access_token(request)
    user_info = token.get("userinfo")

    request.session["user"] = {
        "email": user_info.get("email") or user_info.get("preferred_username", ""),
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "provider": "microsoft",
    }

    return RedirectResponse(url="/chat")


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8002)
