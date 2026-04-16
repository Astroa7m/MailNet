import datetime
import os
import sys
import uuid
from pathlib import Path

from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from copilotkit import LangGraphAGUIAgent
import redis
import uvicorn
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette_session import SessionMiddleware, BackendType

from bson import ObjectId
from common import encrypt_payload, decrypt_payload, refresh_microsoft_token_if_needed, refresh_google_token_if_needed, \
    build_agent, get_or_create_user, db

load_dotenv()

# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("REDIS_URL"))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
is_not_using_copilot_kit = os.getenv("UI_PROVIDER", "custom") == "chainlit"
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

if is_not_using_copilot_kit:
    app.add_middleware(ChainlitAuthMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET"),
    https_only=os.getenv("ENVIRONMENT") == "production",
    cookie_name="session",
    backend_type=BackendType.redis,
    backend_client=redis_client,
    same_site="lax",
    max_age=86400  # 1 day
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

# swtiching uis
UI_PROVIDER = os.getenv("UI_PROVIDER", "custom")

if is_not_using_copilot_kit:
    from chainlit.utils import mount_chainlit

    mount_chainlit(app=app, target=r"C:\Users\ahmed\PycharmProjects\MailNet\app\chatting_ui.py", path="/chat")
else:
    @app.post("/agent")
    async def agent_endpoint(input_data: RunAgentInput, request: Request):
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        azure_token = None
        google_token = None

        encrypted_azure = request.session.get("azure_token")
        if encrypted_azure:
            azure_token = decrypt_payload(encrypted_azure)
            fresh = await refresh_microsoft_token_if_needed(azure_token)
            if fresh != azure_token:
                azure_token = fresh
                request.session["azure_token"] = encrypt_payload(fresh)

        encrypted_google = request.session.get("google_token")
        if encrypted_google:
            google_token = decrypt_payload(encrypted_google)
            fresh = await refresh_google_token_if_needed(google_token)
            if fresh != google_token:
                google_token = fresh
                request.session["google_token"] = encrypt_payload(fresh)

        # restore missing tokens from MongoDB refresh tokens (e.g. second provider after re-login)
        if not encrypted_google or not encrypted_azure:
            user_doc = db["users"].find_one(
                {"_id": ObjectId(user["id"])},
                {"google_refresh_token": 1, "microsoft_refresh_token": 1}
            )
            if user_doc:
                if not encrypted_google and user_doc.get("google_refresh_token"):
                    try:
                        stored_refresh = decrypt_payload(user_doc["google_refresh_token"])["token"]
                        minimal = {
                            "token": "", "refresh_token": stored_refresh,
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                            "scopes": ["https://mail.google.com/"],
                            "expiry": "2000-01-01T00:00:00Z",
                        }
                        google_token = await refresh_google_token_if_needed(minimal)
                        request.session["google_token"] = encrypt_payload(google_token)
                    except Exception:
                        pass

                if not encrypted_azure and user_doc.get("microsoft_refresh_token"):
                    try:
                        stored_refresh = decrypt_payload(user_doc["microsoft_refresh_token"])["token"]
                        minimal = {"refresh_token": stored_refresh, "expires_at": 0}
                        azure_token = await refresh_microsoft_token_if_needed(minimal)
                        request.session["azure_token"] = encrypt_payload(azure_token)
                    except Exception:
                        pass

        user_tz = request.session.get("tz", "UTC")

        # lazy thread creation, only save to DB on first message
        thread_id = input_data.thread_id
        if thread_id and not db["threads"].find_one({"thread_id": thread_id}):
            title = "New conversation"
            user_msgs = [m for m in input_data.messages if m.role == "user"]
            if user_msgs:
                content = user_msgs[-1].content
                if isinstance(content, str):
                    title = content[:60].strip() or title
                elif isinstance(content, list):
                    for part in content:
                        if hasattr(part, "text") and part.text:
                            title = part.text[:60].strip() or title
                            break
            db["threads"].insert_one({
                "thread_id": thread_id,
                "user_id": user["id"],
                "name": title,
                "created_at": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
            })

        graph = await build_agent(azure_token, google_token, user_tz, user_id=user["id"])
        agent = LangGraphAGUIAgent(name="Mailing Agent", description="Helps with everyday mailing tasks", graph=graph)

        encoder = EventEncoder(accept=request.headers.get("accept"))
        return StreamingResponse(
            (encoder.encode(e) async for e in agent.run(input_data)),  # type: ignore
            media_type=encoder.get_content_type()
        )


    @app.get("/agent/health")
    def agent_health():
        return {"status": "ok", "agent": {"name": "Mailing Agent"}}


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/")
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page_direct(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/me")
async def get_me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"providers": 1})
    providers = user_doc.get("providers", [user.get("provider", "google")]) if user_doc else [user.get("provider", "google")]
    return {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "picture": user.get("picture", ""),
        "providers": providers,
    }


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")
        return RedirectResponse(url=FRONT_END_URL)
    return templates.TemplateResponse("login.html", {"request": request})


# Google
@app.get("/login/google")
@limiter.limit("20/minute")
async def login_google(request: Request):
    request.session["tz"] = request.query_params.get("tz", "UTC")
    redirect_uri = request.url_for("auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google", name="auth_google")
@limiter.limit("20/minute")
async def auth_google(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")
    email = user_info["email"]
    refresh_token = token.get("refresh_token")

    google_token_json = {
        "token": token["access_token"],
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "scopes": token["scope"].split(" "),
        "expiry": datetime.datetime.fromtimestamp(token["expires_at"], datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    if request.session.pop("connecting", False):
        # linking flow: attach google account to existing user
        if refresh_token:
            db["users"].update_one(
                {"_id": ObjectId(request.session["user"]["id"])},
                {"$set": {"google_refresh_token": encrypt_payload({"token": refresh_token})}}
            )
        else:
            user_doc = db["users"].find_one({"_id": ObjectId(request.session["user"]["id"])})
            if user_doc and user_doc.get("google_refresh_token"):
                refresh_token = decrypt_payload(user_doc["google_refresh_token"])["token"]
                google_token_json["refresh_token"] = refresh_token

        # TODO: merge orphan document if another user already has this google_email
        db["users"].update_one(
            {"_id": ObjectId(request.session["user"]["id"])},
            {"$set": {"google_email": email}, "$addToSet": {"providers": "google"}}
        )
        request.session["google_token"] = encrypt_payload(google_token_json)
        FRONT_END_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    else:
        # normal login flow
        name = user_info.get("name", "")
        picture = user_info.get("picture", "")
        user = get_or_create_user(email, name, picture, "google")
        request.session["user"] = {
            "id": user["_id"], "email": email,
            "name": name, "picture": picture, "provider": "google",
        }
        if refresh_token:
            db["users"].update_one(
                {"google_email": email},
                {"$set": {"google_refresh_token": encrypt_payload({"token": refresh_token})}}
            )
        else:
            user_doc = db["users"].find_one({"google_email": email})
            if user_doc and user_doc.get("google_refresh_token"):
                refresh_token = decrypt_payload(user_doc["google_refresh_token"])["token"]
                google_token_json["refresh_token"] = refresh_token

        request.session["google_token"] = encrypt_payload(google_token_json)
        FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")

    return RedirectResponse(url=FRONT_END_URL)


# Microsoft
@app.get("/login/microsoft")
@limiter.limit("20/minute")
async def login_microsoft(request: Request):
    request.session["tz"] = request.query_params.get("tz", "UTC")
    redirect_uri = request.url_for("auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@app.get("/auth/microsoft", name="auth_microsoft")
@limiter.limit("20/minute")
async def auth_microsoft(request: Request):
    try:
        token = await oauth.microsoft.authorize_access_token(
            request,
            claims_options={"iss": {"essential": False}}
        )
        user_info = token.get("userinfo")
        email = user_info.get("email") or user_info.get("preferred_username", "")
        refresh_token = token.get("refresh_token")

        if request.session.pop("connecting", False):
            # linking flow: attach microsoft account to existing user
            set_fields = {"outlook_email": email}
            if refresh_token:
                set_fields["microsoft_refresh_token"] = encrypt_payload({"token": refresh_token})

            # TODO: merge orphan document if another user already has this outlook_email
            db["users"].update_one(
                {"_id": ObjectId(request.session["user"]["id"])},
                {"$set": set_fields, "$addToSet": {"providers": "microsoft"}}
            )
            request.session["azure_token"] = encrypt_payload(dict(token))
            FRONT_END_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
        else:
            # — normal login flow —
            name = user_info.get("name", "")
            picture = user_info.get("picture", "")
            user = get_or_create_user(email, name, picture, "microsoft")
            request.session["user"] = {
                "id": user["_id"], "email": email,
                "name": name, "picture": picture, "provider": "microsoft",
            }
            if refresh_token:
                db["users"].update_one(
                    {"outlook_email": email},
                    {"$set": {"microsoft_refresh_token": encrypt_payload({"token": refresh_token})}}
                )
            request.session["azure_token"] = encrypt_payload(dict(token))
            FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")

        return RedirectResponse(url=FRONT_END_URL)
    except OAuthError:
        return RedirectResponse(url="/")


@app.get("/connect/google")
async def connect_google(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.session["connecting"] = True
    redirect_uri = request.url_for("auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri, prompt="select_account consent")


@app.get("/connect/microsoft")
async def connect_microsoft(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.session["connecting"] = True
    redirect_uri = request.url_for("auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri, prompt="select_account")


@app.get("/preferences")
async def get_preferences(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"preferences": 1})
    if not user_doc or "preferences" not in user_doc:
        from common import DEFAULT_PREFERENCES
        return DEFAULT_PREFERENCES.copy()
    return user_doc["preferences"]


@app.patch("/preferences")
async def update_preferences(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    updates = await request.json()
    set_fields = {f"preferences.{k}": v for k, v in updates.items()}
    db["users"].update_one({"_id": ObjectId(user["id"])}, {"$set": set_fields})
    return {"ok": True}


@app.get("/threads")
async def get_threads(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    threads = list(db["threads"].find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("created_at", -1))
    return threads


@app.post("/threads")
async def create_thread(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    thread = {
        "thread_id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": "New conversation",
        "created_at": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    }
    db["threads"].insert_one(thread)
    thread.pop("_id", None)
    return thread


@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = db["threads"].delete_one({"thread_id": thread_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8002)
