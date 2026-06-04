from __future__ import annotations

import csv
import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTENSIONS = {"gif", "jpeg", "jpg", "png", "webp"}
ALLOWED_TIMETABLE_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {"pdf"}
ALLOWED_IMPORT_EXTENSIONS = {"csv", "txt"}
DEFAULT_BAND_DURATION_MINUTES = 60
DEFAULT_SECRET_KEY = "change-this-secret"
INSECURE_SECRET_KEYS = {
    DEFAULT_SECRET_KEY,
    "replace-this-with-a-random-secret",
    "replace-with-a-generated-secret",
}
TIMELINE_PIXELS_PER_MINUTE = 3
FESTIVAL_DAY_START_MINUTES = 10 * 60 + 30
FESTIVAL_DAY_END_MINUTES = 28 * 60
FESTIVAL_DAY_OVERNIGHT_CUTOFF_MINUTES = 4 * 60
PUBLIC_DEPLOYMENT_ENV_VARS = (
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
)
PRODUCTION_ENV_VALUES = {"prod", "production"}


def resolve_local_ssl_context(root_path: str | Path) -> tuple[str, str] | None:
    if os.environ.get("RENDER") == "true":
        return None

    explicit_cert = os.environ.get("SSL_CERT_PATH")
    explicit_key = os.environ.get("SSL_KEY_PATH")
    local_https_enabled = os.environ.get("LOCAL_HTTPS") == "1"

    if not local_https_enabled and not (explicit_cert and explicit_key):
        return None

    root_path = Path(root_path)
    cert_path = Path(explicit_cert) if explicit_cert else root_path / "certs" / "dev-cert.pem"
    key_path = Path(explicit_key) if explicit_key else root_path / "certs" / "dev-key.pem"

    if cert_path.exists() and key_path.exists():
        return (str(cert_path), str(key_path))

    raise FileNotFoundError(
        "HTTPS was requested, but the development certificate files were not found. "
        "Run scripts/generate_dev_cert.sh first or set SSL_CERT_PATH and SSL_KEY_PATH."
    )


def is_public_deployment() -> bool:
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    flask_env = os.environ.get("FLASK_ENV", "").strip().lower()
    return (
        any(os.environ.get(name) for name in PUBLIC_DEPLOYMENT_ENV_VARS)
        or os.environ.get("RENDER") == "true"
        or app_env in PRODUCTION_ENV_VALUES
        or flask_env in PRODUCTION_ENV_VALUES
    )


def validate_deployment_config(app: Flask) -> None:
    if app.config["TESTING"] or not is_public_deployment():
        return

    defaulted_secrets = []
    if str(app.config["SECRET_KEY"]).strip() in INSECURE_SECRET_KEYS:
        defaulted_secrets.append("SECRET_KEY")

    if defaulted_secrets:
        names = ", ".join(defaulted_secrets)
        raise RuntimeError(
            f"Public deployment requires non-default values for: {names}. "
            "Set these in your hosting service's environment variables before deploying."
        )


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    test_config = test_config or {}

    railway_volume_mount_path = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    default_data_root = Path(
        test_config.get("DATA_ROOT")
        or os.environ.get("DATA_ROOT")
        or railway_volume_mount_path
        or Path(app.root_path) / "data"
    )
    database_path = Path(
        test_config.get("DATABASE")
        or os.environ.get("DATABASE_PATH")
        or default_data_root / "festival_finder.db"
    )
    upload_root = Path(
        test_config.get("UPLOAD_ROOT")
        or os.environ.get("UPLOAD_ROOT")
        or default_data_root / "uploads"
    )

    max_upload_mb = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "24"))
    app.config.from_mapping(
        SECRET_KEY=test_config.get("SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or DEFAULT_SECRET_KEY,
        DATABASE=str(database_path),
        UPLOAD_ROOT=str(upload_root),
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_public_deployment(),
        TESTING=bool(test_config.get("TESTING", False)),
    )
    app.config.update(test_config)
    validate_deployment_config(app)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_ROOT"]).mkdir(parents=True, exist_ok=True)
    for subfolder in ("attendees", "timetables"):
        (Path(app.config["UPLOAD_ROOT"]) / subfolder).mkdir(parents=True, exist_ok=True)

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    def close_db(_error: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db() -> None:
        db = sqlite3.connect(app.config["DATABASE"])
        db.execute("PRAGMA foreign_keys = ON")
        with app.open_resource("schema.sql") as schema_file:
            db.executescript(schema_file.read().decode("utf-8"))
        migrate_attendees_schema(db)
        db.commit()
        db.close()

    def migrate_attendees_schema(db: sqlite3.Connection) -> None:
        attendee_columns = db.execute("PRAGMA table_info(attendees)").fetchall()
        if not attendee_columns:
            return

        attendee_column_map = {column[1]: column for column in attendee_columns}
        nullable_columns = ("display_name", "latitude", "longitude", "pov_image", "side_image")
        requires_migration = any(
            attendee_column_map.get(column_name, (None, None, None, None, 0))[3]
            for column_name in nullable_columns
        )
        if not requires_migration:
            return

        db.execute("ALTER TABLE attendees RENAME TO attendees_legacy")
        db.execute(
            """
            CREATE TABLE attendees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                band_id INTEGER NOT NULL,
                display_name TEXT,
                latitude REAL,
                longitude REAL,
                note TEXT,
                pov_image TEXT,
                side_image TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (band_id) REFERENCES bands (id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            INSERT INTO attendees (
                id,
                band_id,
                display_name,
                latitude,
                longitude,
                note,
                pov_image,
                side_image,
                created_at
            )
            SELECT
                id,
                band_id,
                display_name,
                latitude,
                longitude,
                note,
                pov_image,
                side_image,
                created_at
            FROM attendees_legacy
            """
        )
        db.execute("DROP TABLE attendees_legacy")
        db.execute("CREATE INDEX IF NOT EXISTS idx_attendees_band_id ON attendees (band_id)")

    def get_owned_attendee_ids() -> set[int]:
        owned_ids = session.get("owned_attendee_ids", [])
        normalized_ids = set()
        for raw_id in owned_ids:
            try:
                normalized_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue
        return normalized_ids

    def get_owned_favorite_ids() -> set[int]:
        owned_ids = session.get("owned_favorite_ids", [])
        normalized_ids = set()
        for raw_id in owned_ids:
            try:
                normalized_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue
        return normalized_ids

    def session_owns_attendee(attendee_id: int) -> bool:
        return attendee_id in get_owned_attendee_ids()

    def session_owns_favorite(favorite_id: int) -> bool:
        return favorite_id in get_owned_favorite_ids()

    def remember_owned_attendee(attendee_id: int) -> None:
        owned_ids = get_owned_attendee_ids()
        owned_ids.add(attendee_id)
        session["owned_attendee_ids"] = sorted(owned_ids)

    def remember_owned_favorite(favorite_id: int) -> None:
        owned_ids = get_owned_favorite_ids()
        owned_ids.add(favorite_id)
        session["owned_favorite_ids"] = sorted(owned_ids)

    def forget_owned_attendee(attendee_id: int) -> None:
        owned_ids = get_owned_attendee_ids()
        if attendee_id not in owned_ids:
            return

        owned_ids.remove(attendee_id)
        session["owned_attendee_ids"] = sorted(owned_ids)

    def forget_owned_favorite(favorite_id: int) -> None:
        owned_ids = get_owned_favorite_ids()
        if favorite_id not in owned_ids:
            return

        owned_ids.remove(favorite_id)
        session["owned_favorite_ids"] = sorted(owned_ids)

    def can_manage_attendee(attendee_id: int) -> bool:
        return True

    def can_manage_favorite(favorite_id: int) -> bool:
        return True

    def get_band_or_404(band_id: int) -> sqlite3.Row:
        band = get_db().execute(
            """
            SELECT
                b.*,
                COUNT(DISTINCT a.id) AS attendee_count,
                COUNT(DISTINCT f.id) AS favorite_count
            FROM bands b
            LEFT JOIN attendees a ON a.band_id = b.id
            LEFT JOIN favorites f ON f.band_id = b.id
            WHERE b.id = ?
            GROUP BY b.id
            """,
            (band_id,),
        ).fetchone()
        if band is None:
            abort(404)
        return band

    def parse_coordinate(raw_value: str, minimum: float, maximum: float, label: str) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a valid number.") from exc
        if value < minimum or value > maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        return value

    def is_image_file(path: str | None) -> bool:
        if not path or "." not in path:
            return False
        extension = path.rsplit(".", 1)[1].lower()
        return extension in ALLOWED_IMAGE_EXTENSIONS

    def attendee_display_name(value: str | None) -> str:
        cleaned = (value or "").strip()
        return cleaned or "Anonymous"

    def save_upload(file_storage, folder: str, allowed_extensions: set[str]) -> str | None:
        if file_storage is None or not file_storage.filename:
            return None

        original_name = secure_filename(file_storage.filename)
        if not original_name or "." not in original_name:
            raise ValueError("Upload must include a file extension.")

        extension = original_name.rsplit(".", 1)[1].lower()
        if extension not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"Unsupported file type. Allowed: {allowed}.")

        filename = f"{uuid.uuid4().hex}_{original_name}"
        relative_path = Path(folder) / filename
        absolute_path = Path(app.config["UPLOAD_ROOT"]) / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        file_storage.save(absolute_path)
        return relative_path.as_posix()

    def delete_uploaded_file(path: str | None) -> None:
        if not path:
            return

        absolute_path = Path(app.config["UPLOAD_ROOT"]) / path
        try:
            absolute_path.unlink(missing_ok=True)
        except OSError:
            # Ignore cleanup failures so the entry can still be removed.
            pass

    def parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def normalize_clock_value(value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()
        if not cleaned:
            return None

        for fmt in ("%H:%M", "%H.%M", "%H:%M:%S"):
            try:
                return datetime.strptime(cleaned, fmt).strftime("%H:%M")
            except ValueError:
                continue

        raise ValueError("Times must use HH:MM format, for example 20:30.")

    def parse_clock_minutes(value: str | None) -> int | None:
        normalized = normalize_clock_value(value)
        if not normalized:
            return None

        parsed = datetime.strptime(normalized, "%H:%M")
        return parsed.hour * 60 + parsed.minute

    def normalize_festival_day_minutes(value: str | None) -> int | None:
        raw_minutes = parse_clock_minutes(value)
        if raw_minutes is None:
            return None

        if raw_minutes <= FESTIVAL_DAY_OVERNIGHT_CUTOFF_MINUTES:
            return raw_minutes + (24 * 60)

        return raw_minutes

    def format_clock_minutes(total_minutes: int) -> str:
        normalized = max(total_minutes, 0)
        hours = (normalized // 60) % 24
        minutes = normalized % 60
        return f"{hours:02d}:{minutes:02d}"

    def get_attendee_or_404(band_id: int, attendee_id: int) -> sqlite3.Row:
        attendee = get_db().execute(
            """
            SELECT *
            FROM attendees
            WHERE id = ? AND band_id = ?
            """,
            (attendee_id, band_id),
        ).fetchone()
        if attendee is None:
            abort(404)
        return attendee

    def get_favorite_or_404(band_id: int, favorite_id: int) -> sqlite3.Row:
        favorite = get_db().execute(
            """
            SELECT *
            FROM favorites
            WHERE id = ? AND band_id = ?
            """,
            (favorite_id, band_id),
        ).fetchone()
        if favorite is None:
            abort(404)
        return favorite

    def get_owned_favorite_for_band(band_id: int) -> sqlite3.Row | None:
        owned_favorite_ids = sorted(get_owned_favorite_ids())
        if not owned_favorite_ids:
            return None

        placeholders = ",".join("?" for _ in owned_favorite_ids)
        return get_db().execute(
            f"""
            SELECT *
            FROM favorites
            WHERE band_id = ?
              AND id IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            [band_id, *owned_favorite_ids],
        ).fetchone()

    def parse_delimited_import(file_storage) -> list[list[str]]:
        if file_storage is None or not file_storage.filename:
            raise ValueError("Choose a CSV file exported from Excel.")

        filename = secure_filename(file_storage.filename)
        if "." not in filename:
            raise ValueError("Import file must include an extension.")

        extension = filename.rsplit(".", 1)[1].lower()
        if extension not in ALLOWED_IMPORT_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_IMPORT_EXTENSIONS))
            raise ValueError(f"Unsupported import type. Allowed: {allowed}.")

        raw_bytes = file_storage.read()
        if not raw_bytes:
            raise ValueError("Import file is empty.")

        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1")

        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(io.StringIO(text), dialect)
        rows = []
        for row in reader:
            cleaned_row = [cell.strip() for cell in row]
            if any(cleaned_row):
                rows.append(cleaned_row)

        if not rows:
            raise ValueError("Import file does not contain any timetable rows.")

        return rows

    def looks_like_import_header(row: list[str]) -> bool:
        if len(row) < 4:
            return False

        normalized = [cell.strip().lower() for cell in row[:4]]
        return (
            normalized[0] in {"stage", "stage name"}
            and normalized[1] in {"start", "start time", "begin", "begin time"}
            and normalized[2] in {"end", "end time", "stop", "stop time"}
            and normalized[3] in {"band", "band name", "artist", "artist name"}
        )

    def delete_band_files(band_id: int) -> None:
        db = get_db()
        band = db.execute(
            """
            SELECT timetable_file
            FROM bands
            WHERE id = ?
            """,
            (band_id,),
        ).fetchone()
        attendees = db.execute(
            """
            SELECT pov_image, side_image
            FROM attendees
            WHERE band_id = ?
            """,
            (band_id,),
        ).fetchall()

        if band is not None:
            delete_uploaded_file(band["timetable_file"])

        for attendee in attendees:
            delete_uploaded_file(attendee["pov_image"])
            delete_uploaded_file(attendee["side_image"])

    def delete_bands_and_related_files(band_ids: list[int]) -> None:
        if not band_ids:
            return

        db = get_db()
        placeholders = ",".join("?" for _ in band_ids)

        band_rows = db.execute(
            f"""
            SELECT timetable_file
            FROM bands
            WHERE id IN ({placeholders})
            """,
            band_ids,
        ).fetchall()
        attendee_rows = db.execute(
            f"""
            SELECT pov_image, side_image
            FROM attendees
            WHERE band_id IN ({placeholders})
            """,
            band_ids,
        ).fetchall()

        for band_row in band_rows:
            delete_uploaded_file(band_row["timetable_file"])

        for attendee_row in attendee_rows:
            delete_uploaded_file(attendee_row["pov_image"])
            delete_uploaded_file(attendee_row["side_image"])

        db.execute(f"DELETE FROM bands WHERE id IN ({placeholders})", band_ids)
        db.commit()

    def build_attendee_payload(attendee: sqlite3.Row) -> dict:
        has_location = attendee["latitude"] is not None and attendee["longitude"] is not None
        location = f"{attendee['latitude']},{attendee['longitude']}" if has_location else None
        return {
            "id": attendee["id"],
            "display_name": attendee_display_name(attendee["display_name"]),
            "latitude": attendee["latitude"],
            "longitude": attendee["longitude"],
            "note": attendee["note"] or "",
            "created_at": attendee["created_at"],
            "pov_image_url": (
                url_for("uploaded_file", filename=attendee["pov_image"])
                if attendee["pov_image"]
                else None
            ),
            "side_image_url": (
                url_for("uploaded_file", filename=attendee["side_image"])
                if attendee["side_image"]
                else None
            ),
            "map_url": (
                "https://www.openstreetmap.org/"
                f"?mlat={attendee['latitude']}&mlon={attendee['longitude']}"
                f"#map=18/{attendee['latitude']}/{attendee['longitude']}"
            )
            if has_location
            else None,
            "directions_url": f"https://maps.apple.com/?daddr={location}&dirflg=w" if has_location else None,
            "ios_app_directions_url": f"maps://?daddr={location}&dirflg=w" if has_location else None,
        }

    def build_schedule_days(bands: list[sqlite3.Row]) -> list[dict]:
        bands_by_date: dict[str, list[dict]] = {}

        for band in bands:
            start_minute = normalize_festival_day_minutes(band["start_time"])
            if start_minute is None:
                continue

            end_minute = normalize_festival_day_minutes(band["end_time"])
            if end_minute is None or end_minute <= start_minute:
                end_minute = start_minute + DEFAULT_BAND_DURATION_MINUTES

            stage_name = (band["stage_name"] or "").strip() or "Stage TBA"
            bands_by_date.setdefault(band["performance_date"], []).append(
                {
                    "band": band,
                    "start_minute": start_minute,
                    "end_minute": end_minute,
                    "stage_name": stage_name,
                }
            )

        schedule_days = []
        hour_width = TIMELINE_PIXELS_PER_MINUTE * 60

        for date_key in sorted(bands_by_date):
            day_items = bands_by_date[date_key]
            day_start = FESTIVAL_DAY_START_MINUTES
            day_end = FESTIVAL_DAY_END_MINUTES

            ticks = []
            for minute in range(day_start, day_end, 60):
                ticks.append(
                    {
                        "label": format_clock_minutes(minute),
                        "left": (minute - day_start) * TIMELINE_PIXELS_PER_MINUTE,
                    }
                )
            ticks.append(
                {
                    "label": format_clock_minutes(day_end),
                    "left": (day_end - day_start) * TIMELINE_PIXELS_PER_MINUTE,
                }
            )

            stage_rows_by_key: dict[str, dict] = {}
            for item in day_items:
                band = item["band"]
                stage_key = f"{band['festival_name']}::{item['stage_name']}"
                visual_start = min(max(item["start_minute"], day_start), day_end)
                visual_end = min(max(item["end_minute"], visual_start + 1), day_end)
                row = stage_rows_by_key.setdefault(
                    stage_key,
                    {
                        "festival_name": band["festival_name"],
                        "stage_name": item["stage_name"],
                        "sort_start": item["start_minute"],
                        "bands": [],
                    },
                )
                row["sort_start"] = min(row["sort_start"], item["start_minute"])
                row["bands"].append(
                    {
                        "id": band["id"],
                        "band_name": band["band_name"],
                        "festival_name": band["festival_name"],
                        "attendee_count": band["attendee_count"],
                        "favorite_count": band["favorite_count"],
                        "start_time": band["start_time"],
                        "end_time": band["end_time"],
                        "has_timetable": bool(band["timetable_file"]),
                        "left": (visual_start - day_start) * TIMELINE_PIXELS_PER_MINUTE,
                        "width": max(
                            (visual_end - visual_start) * TIMELINE_PIXELS_PER_MINUTE,
                            72,
                        ),
                    }
                )

            stage_rows = sorted(
                stage_rows_by_key.values(),
                key=lambda row: (
                    row["sort_start"],
                    row["festival_name"].lower(),
                    row["stage_name"].lower(),
                ),
            )
            for row in stage_rows:
                row["bands"].sort(
                    key=lambda band: (
                        normalize_festival_day_minutes(band["start_time"]) or 0,
                        normalize_festival_day_minutes(band["end_time"]) or 0,
                        band["band_name"].lower(),
                    )
                )

            schedule_days.append(
                {
                    "date": date_key,
                    "day_start": day_start,
                    "day_end": day_end,
                    "ticks": ticks,
                    "hour_width": hour_width,
                    "pixels_per_minute": TIMELINE_PIXELS_PER_MINUTE,
                    "timeline_width": (day_end - day_start) * TIMELINE_PIXELS_PER_MINUTE,
                    "stage_rows": stage_rows,
                }
            )

        return schedule_days

    def build_stage_groups(bands: list[sqlite3.Row]) -> list[dict]:
        grouped: dict[tuple[str, str, str], dict] = {}

        for band in bands:
            stage_name_value = (band["stage_name"] or "").strip()
            stage_name_display = stage_name_value or "Stage TBA"
            start_minute = normalize_festival_day_minutes(band["start_time"]) or FESTIVAL_DAY_START_MINUTES
            end_minute = normalize_festival_day_minutes(band["end_time"])
            if end_minute is None or end_minute <= start_minute:
                end_minute = start_minute + DEFAULT_BAND_DURATION_MINUTES

            key = (band["performance_date"], band["festival_name"], stage_name_value)
            entry = grouped.setdefault(
                key,
                {
                    "performance_date": band["performance_date"],
                    "festival_name": band["festival_name"],
                    "stage_name_value": stage_name_value,
                    "stage_name_display": stage_name_display,
                    "band_count": 0,
                    "attendee_count": 0,
                    "favorite_count": 0,
                    "sort_start": start_minute,
                    "sort_end": end_minute,
                },
            )
            entry["band_count"] += 1
            entry["attendee_count"] += band["attendee_count"]
            entry["favorite_count"] += band["favorite_count"]
            entry["sort_start"] = min(entry["sort_start"], start_minute)
            entry["sort_end"] = max(entry["sort_end"], end_minute)

        days: dict[str, list[dict]] = {}
        for entry in grouped.values():
            entry["time_range"] = (
                f"{format_clock_minutes(entry['sort_start'])} - "
                f"{format_clock_minutes(entry['sort_end'])}"
            )
            days.setdefault(entry["performance_date"], []).append(entry)

        grouped_days = []
        for date_key in sorted(days):
            stages = sorted(
                days[date_key],
                key=lambda stage: (
                    stage["sort_start"],
                    stage["festival_name"].lower(),
                    stage["stage_name_display"].lower(),
                ),
            )
            grouped_days.append({"date": date_key, "stages": stages})

        return grouped_days

    @app.context_processor
    def template_helpers() -> dict:
        def openstreetmap_place_url(latitude: float, longitude: float) -> str:
            return (
                "https://www.openstreetmap.org/"
                f"?mlat={latitude}&mlon={longitude}#map=18/{latitude}/{longitude}"
            )

        def apple_maps_directions_url(latitude: float, longitude: float) -> str:
            return f"https://maps.apple.com/?daddr={latitude},{longitude}&dirflg=w"

        def apple_maps_ios_app_url(latitude: float, longitude: float) -> str:
            return f"maps://?daddr={latitude},{longitude}&dirflg=w"

        return {
            "is_admin": True,
            "can_manage_attendee": can_manage_attendee,
            "can_manage_favorite": can_manage_favorite,
            "attendee_display_name": attendee_display_name,
            "is_image_file": is_image_file,
            "openstreetmap_place_url": openstreetmap_place_url,
            "apple_maps_directions_url": apple_maps_directions_url,
            "apple_maps_ios_app_url": apple_maps_ios_app_url,
        }

    @app.template_filter("readable_date")
    def readable_date(value: str | None) -> str:
        if not value:
            return "Date not set"
        return datetime.strptime(value, "%Y-%m-%d").strftime("%A, %d %b %Y")

    @app.template_filter("readable_time")
    def readable_time(value: str | None) -> str:
        if not value:
            return "--:--"
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")

    @app.template_filter("relative_time")
    def relative_time(value: str | None) -> str:
        timestamp = parse_timestamp(value)
        if timestamp is None:
            return "just now"

        elapsed_seconds = max(
            int((datetime.now(timezone.utc) - timestamp).total_seconds()),
            0,
        )
        if elapsed_seconds < 60:
            return "just now"

        intervals = (
            (60, "min"),
            (24, "hr"),
            (7, "day"),
            (4, "week"),
        )
        current_value = elapsed_seconds // 60

        for limit, label in intervals:
            if current_value < limit:
                suffix = "" if current_value == 1 else "s"
                return f"{current_value} {label}{suffix} ago"
            current_value //= limit

        suffix = "" if current_value == 1 else "s"
        return f"{current_value} month{suffix} ago"

    @app.errorhandler(413)
    def file_too_large(_error):
        flash("Upload too large. Keep files under 24 MB.", "error")
        return redirect(request.referrer or url_for("index"))

    def render_home(active_tab: str) -> str:
        db = get_db()
        bands = db.execute(
            """
            SELECT
                b.*,
                COUNT(DISTINCT a.id) AS attendee_count,
                COUNT(DISTINCT f.id) AS favorite_count
            FROM bands b
            LEFT JOIN attendees a ON a.band_id = b.id
            LEFT JOIN favorites f ON f.band_id = b.id
            GROUP BY b.id
            ORDER BY b.performance_date ASC, b.start_time ASC, b.created_at DESC
            """
        ).fetchall()
        total_attendees = db.execute("SELECT COUNT(*) AS count FROM attendees").fetchone()["count"]
        total_favorites = db.execute("SELECT COUNT(*) AS count FROM favorites").fetchone()["count"]
        schedule_days = build_schedule_days(bands)
        stage_groups = build_stage_groups(bands)
        active_tab = active_tab.strip().lower()
        if active_tab not in {"overview", "manage"}:
            active_tab = "overview"
        return render_template(
            "index.html",
            bands=bands,
            active_tab=active_tab,
            schedule_days=schedule_days,
            stage_groups=stage_groups,
            total_bands=len(bands),
            total_attendees=total_attendees,
            total_favorites=total_favorites,
        )

    @app.get("/")
    def index():
        return render_home(request.args.get("tab", "overview"))

    @app.get("/admin")
    def admin_page():
        return render_home("manage")

    @app.post("/bands")
    def create_band():
        band_name = request.form.get("band_name", "").strip()
        festival_name = request.form.get("festival_name", "").strip()
        stage_name = request.form.get("stage_name", "").strip()
        performance_date = request.form.get("performance_date", "").strip()
        start_time_raw = request.form.get("start_time", "").strip()
        end_time_raw = request.form.get("end_time", "").strip()
        timetable_notes = request.form.get("timetable_notes", "").strip()
        next_url = request.form.get("next", "").strip()

        errors = []
        if not band_name:
            errors.append("Band name is required.")
        if not festival_name:
            errors.append("Festival name is required.")
        if not performance_date:
            errors.append("Performance date is required.")
        if not start_time_raw:
            errors.append("Start time is required.")

        try:
            start_time = normalize_clock_value(start_time_raw)
            end_time = normalize_clock_value(end_time_raw)
        except ValueError as exc:
            errors.append(str(exc))
            start_time = None
            end_time = None

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(next_url or url_for("index", tab="manage"))

        try:
            timetable_file = save_upload(
                request.files.get("timetable_file"),
                "timetables",
                ALLOWED_TIMETABLE_EXTENSIONS,
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(next_url or url_for("index", tab="manage"))

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO bands (
                band_name,
                festival_name,
                stage_name,
                performance_date,
                start_time,
                end_time,
                timetable_notes,
                timetable_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                band_name,
                festival_name,
                stage_name,
                performance_date,
                start_time,
                end_time or None,
                timetable_notes,
                timetable_file,
            ),
        )
        db.commit()
        flash("Band slot created.", "success")
        return redirect(next_url or url_for("band_detail", band_id=cursor.lastrowid))

    @app.post("/bands/import")
    def import_bands():
        festival_name = request.form.get("festival_name", "").strip()
        performance_date = request.form.get("performance_date", "").strip()

        errors = []
        if not festival_name:
            errors.append("Festival name is required for import.")
        if not performance_date:
            errors.append("Performance date is required for import.")

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("index", tab="manage"))

        try:
            rows = parse_delimited_import(request.files.get("timetable_import_file"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index", tab="manage"))

        data_rows = rows[1:] if rows and looks_like_import_header(rows[0]) else rows
        if not data_rows:
            flash("Import file only contains headers. Add timetable rows first.", "error")
            return redirect(url_for("index", tab="manage"))

        imported_bands = []
        for row_number, row in enumerate(data_rows, start=2 if rows and looks_like_import_header(rows[0]) else 1):
            if len(row) < 4:
                flash(
                    f"Row {row_number} must have 4 columns: stage, start, end, band name.",
                    "error",
                )
                return redirect(url_for("index", tab="manage"))

            stage_name = row[0].strip()
            start_raw = row[1].strip()
            end_raw = row[2].strip()
            band_name = row[3].strip()

            if not band_name:
                flash(f"Row {row_number} is missing the band name.", "error")
                return redirect(url_for("index", tab="manage"))

            try:
                start_time = normalize_clock_value(start_raw)
                end_time = normalize_clock_value(end_raw)
            except ValueError as exc:
                flash(f"Row {row_number}: {exc}", "error")
                return redirect(url_for("index", tab="manage"))

            if not start_time:
                flash(f"Row {row_number} is missing the start time.", "error")
                return redirect(url_for("index", tab="manage"))

            imported_bands.append(
                (
                    band_name,
                    festival_name,
                    stage_name or None,
                    performance_date,
                    start_time,
                    end_time,
                    "",
                    None,
                )
            )

        db = get_db()
        db.executemany(
            """
            INSERT INTO bands (
                band_name,
                festival_name,
                stage_name,
                performance_date,
                start_time,
                end_time,
                timetable_notes,
                timetable_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            imported_bands,
        )
        db.commit()
        flash(
            f"Imported {len(imported_bands)} bands from the timetable file.",
            "success",
        )
        return redirect(url_for("index", tab="manage"))

    @app.post("/bands/<int:band_id>/delete")
    def delete_band(band_id: int):
        band = get_band_or_404(band_id)
        delete_band_files(band_id)

        db = get_db()
        db.execute("DELETE FROM bands WHERE id = ?", (band_id,))
        db.commit()

        flash(f"{band['band_name']} was deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/stages/delete")
    def delete_stage():
        performance_date = request.form.get("performance_date", "").strip()
        festival_name = request.form.get("festival_name", "").strip()
        stage_name_value = request.form.get("stage_name_value", "").strip()

        if not performance_date or not festival_name:
            flash("Stage delete request is missing festival/day information.", "error")
            return redirect(url_for("index", tab="manage"))

        db = get_db()
        bands = db.execute(
            """
            SELECT id
            FROM bands
            WHERE performance_date = ?
              AND festival_name = ?
              AND COALESCE(stage_name, '') = ?
            ORDER BY start_time ASC, id ASC
            """,
            (performance_date, festival_name, stage_name_value),
        ).fetchall()

        band_ids = [band["id"] for band in bands]
        if not band_ids:
            flash("That stage no longer exists.", "error")
            return redirect(url_for("index", tab="manage"))

        stage_label = stage_name_value or "Stage TBA"
        delete_bands_and_related_files(band_ids)
        flash(
            f"{stage_label} on {performance_date} was deleted from {festival_name}.",
            "success",
        )
        return redirect(url_for("index", tab="manage"))

    @app.get("/bands/<int:band_id>")
    def band_detail(band_id: int):
        band = get_band_or_404(band_id)
        attendees = get_db().execute(
            """
            SELECT *
            FROM attendees
            WHERE band_id = ?
            ORDER BY created_at DESC
            """,
            (band_id,),
        ).fetchall()
        favorites = get_db().execute(
            """
            SELECT *
            FROM favorites
            WHERE band_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (band_id,),
        ).fetchall()
        return render_template(
            "band_detail.html",
            band=band,
            attendees=attendees,
            favorites=favorites,
        )

    @app.post("/bands/<int:band_id>/favorites")
    def create_favorite(band_id: int):
        band = get_band_or_404(band_id)
        display_name = request.form.get("display_name", "").strip()
        if not display_name:
            flash("Name is required to favorite a band.", "error")
            return redirect(url_for("band_detail", band_id=band["id"]))

        existing_owned_favorite = get_owned_favorite_for_band(band["id"])
        if existing_owned_favorite is not None:
            flash(f"You already favorited {band['band_name']} on this device.", "error")
            return redirect(url_for("band_detail", band_id=band["id"]))

        db = get_db()
        db.execute(
            """
            INSERT INTO favorites (
                band_id,
                display_name
            ) VALUES (?, ?)
            """,
            (band["id"], display_name),
        )
        favorite_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        remember_owned_favorite(favorite_id)
        flash(f"{display_name} favorited {band['band_name']}.", "success")
        return redirect(url_for("band_detail", band_id=band["id"]))

    @app.post("/bands/<int:band_id>/attendees")
    def create_attendee(band_id: int):
        band = get_band_or_404(band_id)
        display_name = request.form.get("display_name", "").strip() or None
        note = request.form.get("note", "").strip() or None
        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = None
        longitude = None
        if latitude_raw and longitude_raw:
            try:
                latitude = parse_coordinate(latitude_raw, -90.0, 90.0, "Latitude")
                longitude = parse_coordinate(longitude_raw, -180.0, 180.0, "Longitude")
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("band_detail", band_id=band["id"]))

        pov_image = request.files.get("pov_image")
        side_image = request.files.get("side_image")

        pov_path = None
        side_path = None
        try:
            pov_path = save_upload(pov_image, "attendees", ALLOWED_IMAGE_EXTENSIONS)
            side_path = save_upload(side_image, "attendees", ALLOWED_IMAGE_EXTENSIONS)
        except ValueError as exc:
            delete_uploaded_file(pov_path)
            delete_uploaded_file(side_path)
            flash(str(exc), "error")
            return redirect(url_for("band_detail", band_id=band["id"]))

        db = get_db()
        db.execute(
            """
            INSERT INTO attendees (
                band_id,
                display_name,
                latitude,
                longitude,
                note,
                pov_image,
                side_image
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                band["id"],
                display_name,
                latitude,
                longitude,
                note,
                pov_path,
                side_path,
            ),
        )
        attendee_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        remember_owned_attendee(attendee_id)
        flash(f"{attendee_display_name(display_name)} checked in for {band['band_name']}.", "success")
        return redirect(url_for("band_detail", band_id=band["id"]))

    @app.post("/bands/<int:band_id>/attendees/<int:attendee_id>/delete")
    def delete_attendee(band_id: int, attendee_id: int):
        band = get_band_or_404(band_id)
        attendee = get_attendee_or_404(band_id, attendee_id)

        if not can_manage_attendee(attendee["id"]):
            flash("You can only remove your own check-in.", "error")
            return redirect(url_for("band_detail", band_id=band["id"]))

        db = get_db()
        db.execute("DELETE FROM attendees WHERE id = ?", (attendee["id"],))
        db.commit()

        delete_uploaded_file(attendee["pov_image"])
        delete_uploaded_file(attendee["side_image"])
        forget_owned_attendee(attendee["id"])

        flash(
            f"{attendee_display_name(attendee['display_name'])} left the crowd for {band['band_name']}.",
            "success",
        )
        return redirect(url_for("band_detail", band_id=band["id"]))

    @app.post("/bands/<int:band_id>/favorites/<int:favorite_id>/delete")
    def delete_favorite(band_id: int, favorite_id: int):
        band = get_band_or_404(band_id)
        favorite = get_favorite_or_404(band_id, favorite_id)

        if not can_manage_favorite(favorite["id"]):
            flash("You can only remove your own favorite.", "error")
            return redirect(url_for("band_detail", band_id=band["id"]))

        db = get_db()
        db.execute("DELETE FROM favorites WHERE id = ?", (favorite["id"],))
        db.commit()
        forget_owned_favorite(favorite["id"])

        flash(f"{favorite['display_name']} removed {band['band_name']} from favorites.", "success")
        return redirect(url_for("band_detail", band_id=band["id"]))

    @app.get("/api/bands/<int:band_id>/attendees")
    def attendees_api(band_id: int):
        get_band_or_404(band_id)
        attendees = get_db().execute(
            """
            SELECT *
            FROM attendees
            WHERE band_id = ?
            ORDER BY created_at DESC
            """,
            (band_id,),
        ).fetchall()
        return jsonify({"attendees": [build_attendee_payload(attendee) for attendee in attendees]})

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        return send_from_directory(app.config["UPLOAD_ROOT"], filename)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    ssl_context = resolve_local_ssl_context(app.root_path)
    app.run(host="0.0.0.0", port=port, debug=debug_mode, ssl_context=ssl_context)
