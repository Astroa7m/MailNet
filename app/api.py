import datetime
import os

import redis
import uvicorn
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from chainlit.utils import mount_chainlit
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette_session import SessionMiddleware, BackendType

from common import encrypt_payload, decrypt_payload, refresh_microsoft_token_if_needed, refresh_google_token_if_needed

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
            print("[MIDDLEWARE] No user in session, redirecting to login")
            return RedirectResponse(url="/", status_code=303)

        # Refresh Microsoft token if needed, right here before chainlit sees it
        encrypted_azure = request.session.get("azure_token")
        if encrypted_azure:
            try:
                azure_token = decrypt_payload(encrypted_azure)
                fresh_token = await refresh_microsoft_token_if_needed(azure_token)
                if fresh_token != azure_token:
                    print("[MIDDLEWARE] Microsoft token refreshed")
                    request.session["azure_token"] = encrypt_payload(fresh_token)
            except Exception as e:
                print(f"[MIDDLEWARE] Token refresh failed: {e}")

        encrypted_google = request.session.get("google_token")
        if encrypted_google:
            try:
                google_token = decrypt_payload(encrypted_google)
                if not google_token:
                    raise ValueError("google_token decrypted to None")
                fresh_google = await refresh_google_token_if_needed(google_token)
                if fresh_google != google_token:
                    print("[MIDDLEWARE] Google token refreshed")
                    request.session["google_token"] = encrypt_payload(fresh_google)
            except Exception as e:
                print(f"[MIDDLEWARE] Google token refresh failed: {e}")

        # user is authenticated then continue
        response = await call_next(request)
        return response


redis_client = redis.from_url(
    os.getenv("REDIS_URL"),
    encoding="utf-8",
    decode_responses=False,
)

app.add_middleware(ChainlitAuthMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET"),
    https_only=os.getenv("ENVIRONMENT") == "production",
    cookie_name="session",
    backend_type=BackendType.redis,
    backend_client=redis_client,
    same_site="lax",
    max_age=None
)

# for HTML template serving
templates = Jinja2Templates(directory="templates")

oauth = OAuth()

oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    authorize_params={
        "access_type": "offline",
        "prompt": "consent",
    },
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
    email = user_info["email"]
    refresh_token = token.get("refresh_token")
    redis_key = f"google_refresh_token:{email}"

    if refresh_token:
        print("getting refresh from google")
        # save refresh tokens for future logins
        redis_client.set(redis_key, refresh_token)
    else:
        # reuse the one we saved previously
        saved = redis_client.get(redis_key)
        if saved:
            print("getting refresh from redis")
            refresh_token = saved.decode() if isinstance(saved, bytes) else saved

    # for mcp format
    google_token_json = {
        "token": token["access_token"],
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "scopes": token["scope"].split(" "),
        "expiry": datetime.datetime.fromtimestamp(token["expires_at"], datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    request.session['google_token'] = encrypt_payload(google_token_json)
    return RedirectResponse(url="/chat")


# Microsoft

@app.get("/login/microsoft")
async def login_microsoft(request: Request):
    redirect_uri = request.url_for("auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@app.get("/auth/microsoft", name="auth_microsoft")
async def auth_microsoft(request: Request):
    try:
        token = await oauth.microsoft.authorize_access_token(
            request,
            claims_options={
                "iss": {"essential": False}
            }
        )
        user_info = token.get("userinfo")

        request.session["user"] = {
            "email": user_info.get("email") or user_info.get("preferred_username", ""),
            "name": user_info.get("name", ""),
            "picture": user_info.get("picture", ""),
            "provider": "microsoft",
        }

        request.session['azure_token'] = encrypt_payload(dict(token))
        return RedirectResponse(url="/chat")
    except OAuthError:
        return RedirectResponse(url="/")


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8002)
