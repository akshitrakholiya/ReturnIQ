import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# The Google SDK reads GOOGLE_API_KEY etc. from the process environment, not from our settings.
ENV_FILE = os.getenv("ENV_FILE", ".env")  # e.g. ENV_FILE=.env.alloydb to point everything at the cloud database
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "returniq"
    db_user: str = "returniq_app"
    db_password: str = "returniq_app"

    tools_db_user: str = "returniq_tools"
    tools_db_password: str = "returniq_tools"

    # Empty admin user = connect as the current OS user (Homebrew Postgres default).
    admin_db_user: str = ""
    admin_db_password: str = ""

    # Media (local disk for now; swap for Cloud Storage later, see app/services/storage.py)
    media_dir: str = "media_uploads"
    media_signing_secret: str = "dev-secret-change-me"
    public_base_url: str = "http://localhost:8000"
    upload_url_ttl_seconds: int = 900
    max_media_files: int = 5
    max_photo_bytes: int = 10 * 1024 * 1024
    max_video_bytes: int = 50 * 1024 * 1024

    # Agents. "stub" = scripted model, no network. "gemini" = real Gemini via ADK (needs credentials).
    llm_mode: str = "stub"
    return_model: str = "gemini-3-flash-preview"
    media_model: str = "gemini-3.1-flash-lite"  # separate model = separate quota from return_model
    max_return_tool_calls: int = 3
    llm_timeout_seconds: int = 60
    # Tried in order when the primary model times out, hits its quota or returns 5xx (free tier is tight).
    model_fallbacks: str = "gemini-3.1-flash-lite,gemini-3.5-flash-lite"
    llm_retry_attempts: int = 4  # transient 429/5xx from Gemini, exponential backoff
    manual_review_confidence: float = 0.60

    # Flow B (product reports). Thresholds live here so they can be tuned on the demo data.
    report_as_of: str = ""                  # e.g. 2026-10-16: end of every report window; empty = now()
    rca_model: str = ""                     # empty = return_model; set a stronger model if RCA quality needs it
    max_rca_tool_calls: int = 6
    max_qa_tool_calls: int = 5
    min_returns_for_analysis: int = 5       # fewer -> "not enough data yet"
    healthy_rate_multiplier: float = 1.2    # rate <= 1.2x category and not rising -> "looks healthy"
    trend_change_ratio: float = 0.15        # rate moved >= 15% vs the previous period -> rising/falling
    rca_min_returns: int = 5                # a root cause needs >= 5 supporting returns...
    rca_min_share: float = 0.20             # ...and >= 20% of the period's returns
    report_rebuild_min_reviews: int = 3     # rebuild a stale report once 3+ new reviewed returns exist
    feedback_per_cause: int = 15            # comments/notes per top cause in the evidence pack
    report_run_timeout_minutes: int = 10    # a run older than this is considered dead (server restarted)

    @property
    def return_models(self) -> list[str]:
        return _chain(self.return_model, self.model_fallbacks)

    @property
    def rca_models(self) -> list[str]:
        return _chain(self.rca_model or self.return_model, self.model_fallbacks)

    @property
    def as_of(self) -> datetime:
        """End of every Flow B report window (UTC). Same value the SQL views get via returniq_as_of()."""
        if not self.report_as_of:
            return datetime.now(timezone.utc)
        dt = datetime.fromisoformat(self.report_as_of)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def db_options(self) -> str:
        """libpq startup options shared by both engines: pins returniq_as_of() in SQL to REPORT_AS_OF."""
        return f"-c returniq.as_of={self.as_of.isoformat()}" if self.report_as_of else ""

    @property
    def media_models(self) -> list[str]:
        return _chain(self.media_model, self.model_fallbacks)

    def url(self, user: str | None = None, password: str | None = None, db: str | None = None) -> str:
        import urllib.parse
        user = self.db_user if user is None else user
        password = self.db_password if password is None else password
        if user and password is not None:
            auth = f"{urllib.parse.quote_plus(user)}:{urllib.parse.quote_plus(password)}@"
        elif user:
            auth = f"{urllib.parse.quote_plus(user)}@"
        else:
            auth = ""
        return f"postgresql+psycopg://{auth}{self.db_host}:{self.db_port}/{db or self.db_name}"

    @property
    def app_url(self) -> str:
        return self.url()

    @property
    def tools_url(self) -> str:
        return self.url(self.tools_db_user, self.tools_db_password)

    @property
    def admin_url(self) -> str:
        return self.url(self.admin_db_user, self.admin_db_password, db="postgres")



def _chain(primary: str, fallbacks: str) -> list[str]:
    out = [primary]
    for m in (x.strip() for x in fallbacks.split(",")):
        if m and m not in out:
            out.append(m)
    return out


settings = Settings()


def gemini_retry_options():
    from google.genai import types
    return types.HttpRetryOptions(attempts=settings.llm_retry_attempts, initial_delay=1.0, max_delay=10.0,
                                  http_status_codes=[500, 502, 503, 504])  # 429 is handled in analysis.py: it must wait for the quota window
