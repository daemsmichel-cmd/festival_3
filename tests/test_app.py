import io
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pillow_heif import register_heif_opener

from app import create_app, resolve_local_ssl_context


register_heif_opener()


def make_image_upload(size=(1800, 1200), color=(80, 120, 160), image_format="JPEG"):
    image_file = io.BytesIO()
    Image.new("RGB", size, color).save(image_file, format=image_format)
    image_file.seek(0)
    return image_file


def make_heic_upload(size=(1800, 1200), color=(80, 120, 160)):
    image_file = io.BytesIO()
    Image.new("RGB", size, color).save(image_file, format="HEIF")
    image_file.seek(0)
    return image_file


def make_database_upload():
    with tempfile.TemporaryDirectory() as root:
        database_path = Path(root) / "festival_finder.db"
        db = sqlite3.connect(database_path)
        db.executescript(Path("schema.sql").read_text(encoding="utf-8"))
        db.execute(
            """
            INSERT INTO bands (
                id,
                band_name,
                festival_name,
                stage_name,
                performance_date,
                start_time,
                end_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Uploaded Signal",
                "North Field",
                "Main Stage",
                "2026-08-20",
                "19:00",
                "20:00",
            ),
        )
        db.execute(
            """
            INSERT INTO attendees (
                band_id,
                display_name,
                map_x,
                map_y
            ) VALUES (?, ?, ?, ?)
            """,
            (1, "Uploaded Check", 45.0, 55.0),
        )
        db.execute(
            "INSERT INTO favorites (band_id, display_name) VALUES (?, ?)",
            (1, "Uploaded Friend"),
        )
        db.commit()
        db.close()
        database_file = io.BytesIO(database_path.read_bytes())
        database_file.seek(0)
        return database_file


class FestivalFinderTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.upload_root = root / "uploads"

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(root / "test.db"),
                "UPLOAD_ROOT": str(self.upload_root),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_homepage_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Festival Finder", response.data)
        self.assertNotIn(
            b"Scroll sideways, then open a band to check in and see everyone\xe2\x80\x99s photos and position.",
            response.data,
        )
        self.assertIn(b"This device:", response.data)
        self.assertIn(b"/static/js/device_profile.js", response.data)
        self.assertIn(b"/static/js/timetable_overview.js", response.data)
        self.assertIn(b"Check Ins", response.data)
        self.assertIn(b"Favorites", response.data)
        self.assertIn(b"Admin login", response.data)
        self.assertIn(b'href="/check-ins"', response.data)
        self.assertIn(b'href="/admin"', response.data)
        self.assertIn(b'href="/favorites"', response.data)
        self.assertNotIn(b"Log out", response.data)
        self.assertNotIn(b"bands tracked", response.data)
        self.assertNotIn(b"friend check-ins", response.data)
        self.assertNotIn(b"photos per check-in", response.data)

    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_public_deployment_requires_non_default_secrets(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=True):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "SECRET_KEY",
                ):
                    create_app(
                        {
                            "DATABASE": str(Path(root) / "test.db"),
                            "UPLOAD_ROOT": str(Path(root) / "uploads"),
                        }
                    )

    def test_public_deployment_rejects_placeholder_secrets(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(
                os.environ,
                {
                    "RAILWAY_ENVIRONMENT_NAME": "production",
                    "SECRET_KEY": "replace-this-with-a-random-secret",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "SECRET_KEY",
                ):
                    create_app(
                        {
                            "DATABASE": str(Path(root) / "test.db"),
                            "UPLOAD_ROOT": str(Path(root) / "uploads"),
                        }
                    )

    def test_public_deployment_accepts_configured_secrets(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=True):
                app = create_app(
                    {
                        "SECRET_KEY": "production-secret",
                        "DATABASE": str(Path(root) / "test.db"),
                        "UPLOAD_ROOT": str(Path(root) / "uploads"),
                    }
                )

        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])

    def test_existing_attendee_schema_is_migrated_to_optional_fields(self):
        legacy_db_path = Path(self.temp_dir.name) / "legacy.db"
        legacy_db = sqlite3.connect(legacy_db_path)
        legacy_db.executescript(
            """
            CREATE TABLE bands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                band_name TEXT NOT NULL,
                festival_name TEXT NOT NULL,
                stage_name TEXT,
                performance_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                timetable_notes TEXT,
                timetable_file TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE attendees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                band_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                note TEXT,
                pov_image TEXT NOT NULL,
                side_image TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (band_id) REFERENCES bands (id) ON DELETE CASCADE
            );
            """
        )
        legacy_db.commit()
        legacy_db.close()

        migrated_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(legacy_db_path),
                "UPLOAD_ROOT": str(self.upload_root),
            }
        )

        migrated_db = sqlite3.connect(migrated_app.config["DATABASE"])
        attendee_columns = {
            row[1]: row[3]
            for row in migrated_db.execute("PRAGMA table_info(attendees)").fetchall()
        }
        migrated_db.close()

        self.assertEqual(attendee_columns["display_name"], 0)
        self.assertEqual(attendee_columns["latitude"], 0)
        self.assertEqual(attendee_columns["longitude"], 0)
        self.assertEqual(attendee_columns["map_x"], 0)
        self.assertEqual(attendee_columns["map_y"], 0)
        self.assertEqual(attendee_columns["pov_image"], 0)
        self.assertEqual(attendee_columns["side_image"], 0)

    def test_railway_volume_mount_path_is_used_as_default_data_root(self):
        with tempfile.TemporaryDirectory() as volume_root:
            with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": volume_root}, clear=False):
                app = create_app(
                    {
                        "TESTING": True,
                        "SECRET_KEY": "test-secret",
                    }
                )

        self.assertEqual(app.config["DATABASE"], str(Path(volume_root) / "festival_finder.db"))
        self.assertEqual(app.config["UPLOAD_ROOT"], str(Path(volume_root) / "uploads"))

    def test_admin_page_shows_manage_tools_without_login(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Excel CSV import", response.data)
        self.assertIn(b"Upload single band", response.data)
        self.assertIn(b"Export database", response.data)
        self.assertIn(b"Export or restore", response.data)
        self.assertIn(b"Upload database", response.data)
        self.assertIn(b"Manage timetable", response.data)
        self.assertNotIn(b"Log out", response.data)

        query_response = self.client.get("/?tab=manage")
        self.assertEqual(query_response.status_code, 200)
        self.assertIn(b"Excel CSV import", query_response.data)

    def test_manage_routes_do_not_require_login(self):
        response = self.client.post(
            "/bands",
            data={
                "band_name": "Open Route",
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/bands/1", response.headers["Location"])

    def test_database_export_downloads_current_sqlite_database(self):
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Export Signal",
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        favorite_response = self.client.post(
            "/bands/1/favorites",
            data={"display_name": "Export Friend"},
            follow_redirects=False,
        )
        self.assertEqual(favorite_response.status_code, 302)

        response = self.client.get("/database/export")
        self.assertEqual(response.status_code, 200)
        content_disposition = response.headers["Content-Disposition"].lower()
        self.assertIn("attachment", content_disposition)
        self.assertIn("festival_finder.db", content_disposition)

        with tempfile.NamedTemporaryFile(suffix=".db") as temp_export:
            temp_export.write(response.data)
            temp_export.flush()
            exported_db = sqlite3.connect(temp_export.name)
            self.assertEqual(
                exported_db.execute("SELECT band_name FROM bands").fetchone()[0],
                "Export Signal",
            )
            self.assertEqual(
                exported_db.execute("SELECT display_name FROM favorites").fetchone()[0],
                "Export Friend",
            )
            exported_db.close()

    def test_database_upload_replaces_database_and_saves_backup(self):
        band_response = self.client.post(
            "/bands",
            data={
                "band_name": "Existing Signal",
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(band_response.status_code, 302)

        favorite_response = self.client.post(
            "/bands/1/favorites",
            data={"display_name": "Existing Friend"},
            follow_redirects=False,
        )
        self.assertEqual(favorite_response.status_code, 302)

        response = self.client.post(
            "/database/upload",
            data={
                "database_file": (make_database_upload(), "festival_finder.db"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Database uploaded.", response.data)
        self.assertIn(b"Loaded 1 bands, 1 check-ins, and 1 favorites.", response.data)

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"Uploaded Signal", overview_response.data)
        self.assertNotIn(b"Existing Signal", overview_response.data)

        db = sqlite3.connect(self.app.config["DATABASE"])
        self.assertEqual(
            db.execute("SELECT band_name FROM bands").fetchone()[0],
            "Uploaded Signal",
        )
        self.assertEqual(
            db.execute("SELECT display_name FROM favorites").fetchone()[0],
            "Uploaded Friend",
        )
        db.close()

        backup_files = sorted((Path(self.app.config["DATABASE"]).parent / "database_backups").glob("*.db"))
        self.assertEqual(len(backup_files), 1)
        backup_db = sqlite3.connect(backup_files[0])
        self.assertEqual(
            backup_db.execute("SELECT band_name FROM bands").fetchone()[0],
            "Existing Signal",
        )
        self.assertEqual(
            backup_db.execute("SELECT display_name FROM favorites").fetchone()[0],
            "Existing Friend",
        )
        backup_db.close()

    def test_database_upload_rejects_invalid_database_without_replacing_current_data(self):
        band_response = self.client.post(
            "/bands",
            data={
                "band_name": "Still Here",
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(band_response.status_code, 302)

        response = self.client.post(
            "/database/upload",
            data={
                "database_file": (io.BytesIO(b"not a sqlite database"), "festival_finder.db"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Upload must be a valid SQLite database.", response.data)

        db = sqlite3.connect(self.app.config["DATABASE"])
        self.assertEqual(
            db.execute("SELECT band_name FROM bands").fetchone()[0],
            "Still Here",
        )
        db.close()
        backup_dir = Path(self.app.config["DATABASE"]).parent / "database_backups"
        self.assertFalse(backup_dir.exists())

    def test_homepage_groups_bands_by_stage_and_time(self):
        first_response = self.client.post(
            "/bands",
            data={
                "band_name": "North Skyline",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "21:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(first_response.status_code, 302)

        second_response = self.client.post(
            "/bands",
            data={
                "band_name": "Late Echo",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "20:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(second_response.status_code, 302)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Main Stage", response.data)
        self.assertIn(b"Tent Stage", response.data)
        self.assertIn(b"Wednesday, 19 Aug 2026", response.data)
        self.assertIn(b"10:30", response.data)
        self.assertIn(b"04:00", response.data)
        self.assertIn(b'data-schedule-date="2026-08-19"', response.data)
        self.assertIn(b'data-day-start-minutes="630"', response.data)
        self.assertIn(b'data-day-end-minutes="1680"', response.data)
        self.assertIn(b'data-pixels-per-minute="3"', response.data)
        self.assertEqual(response.data.count(b"schedule-row__label"), 2)
        self.assertIn(b"left: 1710px; width: 180px;", response.data)
        self.assertIn(b"left: 1710px; width: 90px;", response.data)
        self.assertNotIn(b"schedule-band schedule-band--active", response.data)

    def test_homepage_places_after_midnight_bands_at_end_of_festival_day(self):
        late_response = self.client.post(
            "/bands",
            data={
                "band_name": "Late Sparks",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "23:30",
                "end_time": "00:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(late_response.status_code, 302)

        after_midnight_response = self.client.post(
            "/bands",
            data={
                "band_name": "Night Bloom",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "01:00",
                "end_time": "02:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(after_midnight_response.status_code, 302)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"23:30", response.data)
        self.assertIn(b"00:30", response.data)
        self.assertIn(b"01:00", response.data)
        self.assertIn(b"02:00", response.data)
        self.assertIn(b"left: 2340px; width: 180px;", response.data)
        self.assertIn(b"left: 2610px; width: 180px;", response.data)

    def test_import_csv_from_excel_export(self):
        response = self.client.post(
            "/bands/import",
            data={
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "timetable_import_file": (
                    io.BytesIO(
                        (
                            "Stage;Start;End;Band Name\n"
                            "Main Stage;20:00;21:00;North Skyline\n"
                            "Tent Stage;20:30;21:15;Late Echo\n"
                        ).encode("utf-8")
                    ),
                    "timetable.csv",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Imported 2 bands from the timetable file.", response.data)
        self.assertIn(b"Main Stage", response.data)
        self.assertIn(b"Tent Stage", response.data)

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"North Skyline", overview_response.data)
        self.assertIn(b"Late Echo", overview_response.data)

    def test_create_band_and_attendee_checkin(self):
        response = self.client.post(
            "/bands",
            data={
                "band_name": "The Twilight Set",
                "festival_name": "North Field",
                "stage_name": "River Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:30",
                "end_time": "21:45",
                "timetable_notes": "Meet by the sound tower after the set.",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The Twilight Set", response.data)
        self.assertIn(b"Favorite this band", response.data)
        self.assertIn(b"Friend position", response.data)
        self.assertNotIn(b"Photos and positions", response.data)
        self.assertIn(b"GMM 2026 map pin", response.data)
        self.assertIn(b"/static/img/gmm2026.png", response.data)
        self.assertIn(b"No map pin selected.", response.data)
        self.assertNotIn(b'data-map-zoom type="range"', response.data)
        self.assertNotIn(b"Friend map", response.data)
        self.assertIn(b"Delete band", response.data)
        self.assertNotIn(b"Latitude", response.data)
        self.assertNotIn(b"Longitude", response.data)
        self.assertNotIn(b"Add your crowd view", response.data)
        self.assertNotIn(b"Share a name, GPS location, POV photo, and side photo.", response.data)
        self.assertNotIn(b'name="note"', response.data)
        self.assertNotIn(b"Notes", response.data)
        self.assertNotIn(b"Tap once to add your position before checking in.", response.data)
        self.assertNotIn(b"iPhone only allows browser location on HTTPS sites.", response.data)
        self.assertIn(b'autocomplete="name"', response.data)
        self.assertGreaterEqual(response.data.count(b'data-remember-last-value="festival-finder-display-name"'), 2)
        self.assertGreaterEqual(response.data.count(b'capture="environment"'), 2)
        self.assertNotIn(b'name="display_name" required', response.data)
        self.assertNotIn(b'name="pov_image" accept="image/*" capture="environment" required', response.data)
        self.assertNotIn(b'name="side_image" accept="image/*" capture="environment" required', response.data)

        timeline_response = self.client.get("/")
        self.assertEqual(timeline_response.status_code, 200)
        self.assertIn(b"Swipe or scroll horizontally to move through the lineup.", timeline_response.data)

        response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Michel",
                "latitude": "51.234567",
                "longitude": "4.123456",
                "map_x": "42.500",
                "map_y": "61.250",
                "note": "Front-left barrier, close to the camera rail.",
                "pov_image": (make_heic_upload(size=(1800, 900)), "pov.heic"),
                "side_image": (make_image_upload(size=(900, 1800)), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Michel", response.data)
        self.assertIn(b"Checked in just now", response.data)
        attendee_files = sorted(self.upload_root.joinpath("attendees").iterdir())
        self.assertEqual(len(attendee_files), 2)
        self.assertTrue(all(path.suffix == ".jpg" for path in attendee_files))
        for attendee_file in attendee_files:
            with Image.open(attendee_file) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertLessEqual(max(image.size), 1280)

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"schedule-band schedule-band--active", overview_response.data)
        self.assertIn(b"Manage timetable", overview_response.data)

        api_response = self.client.get("/api/bands/1/attendees")
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.get_json()
        self.assertEqual(payload["attendees"][0]["display_name"], "Michel")
        self.assertEqual(payload["attendees"][0]["map_x"], 42.5)
        self.assertEqual(payload["attendees"][0]["map_y"], 61.25)
        self.assertEqual(payload["attendees"][0]["festival_map_pin"], {"x": 42.5, "y": 61.25})
        self.assertIn("https://www.openstreetmap.org/", payload["attendees"][0]["map_url"])
        self.assertIn("https://maps.apple.com/?daddr=", payload["attendees"][0]["directions_url"])
        self.assertIn("maps://?daddr=", payload["attendees"][0]["ios_app_directions_url"])

        band_detail_response = self.client.get("/bands/1")
        self.assertEqual(band_detail_response.status_code, 200)
        self.assertIn(b'href="/?tab=overview"', band_detail_response.data)
        self.assertIn(b"Open map", band_detail_response.data)
        self.assertIn(b"Exit crowd", band_detail_response.data)
        self.assertIn(b"--pin-x: 42.5%; --pin-y: 61.25%;", band_detail_response.data)
        self.assertIn(b"data-map-shared-pin", band_detail_response.data)
        self.assertIn(b"festival-map__pin-label", band_detail_response.data)
        self.assertIn("Michel · now".encode(), band_detail_response.data)

        other_client = self.app.test_client()
        other_band_detail_response = other_client.get("/bands/1")
        self.assertEqual(other_band_detail_response.status_code, 200)
        self.assertIn(b"Exit crowd", other_band_detail_response.data)

        delete_response = self.client.post(
            "/bands/1/attendees/1/delete",
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"left the crowd", delete_response.data)
        self.assertIn(b"No one has checked in yet", delete_response.data)
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))

        api_response = self.client.get("/api/bands/1/attendees")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json(), {"attendees": []})

    def test_create_and_delete_band_favorite(self):
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Signal Fires",
                "festival_name": "North Field",
                "performance_date": "2026-08-20",
                "start_time": "19:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        favorite_response = self.client.post(
            "/bands/1/favorites",
            data={"display_name": "Michel"},
            follow_redirects=True,
        )
        self.assertEqual(favorite_response.status_code, 200)
        self.assertIn(b"Michel favorited Signal Fires.", favorite_response.data)
        self.assertIn(b"1 favorites", favorite_response.data)
        self.assertIn(b"Remove favorite", favorite_response.data)

        favorites_page_response = self.client.get("/favorites")
        self.assertEqual(favorites_page_response.status_code, 200)
        self.assertIn(b"Signal Fires", favorites_page_response.data)
        self.assertIn(b"Favourited by", favorites_page_response.data)
        self.assertIn(b"Michel", favorites_page_response.data)
        self.assertIn(b"View band", favorites_page_response.data)
        self.assertIn(b'href="/bands/1"', favorites_page_response.data)

        duplicate_response = self.client.post(
            "/bands/1/favorites",
            data={"display_name": "Michel"},
            follow_redirects=True,
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(b"You already favorited Signal Fires on this device.", duplicate_response.data)

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"0 in crowd \xc2\xb7 1 favorites", overview_response.data)
        self.assertIn(b"schedule-band schedule-band--active", overview_response.data)

        other_client = self.app.test_client()
        other_band_detail_response = other_client.get("/bands/1")
        self.assertEqual(other_band_detail_response.status_code, 200)
        self.assertIn(b"Remove favorite", other_band_detail_response.data)

        delete_response = self.client.post(
            "/bands/1/favorites/1/delete",
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"Michel removed Signal Fires from favorites.", delete_response.data)
        self.assertIn(b"No favorites yet.", delete_response.data)

        empty_favorites_page_response = self.client.get("/favorites")
        self.assertEqual(empty_favorites_page_response.status_code, 200)
        self.assertIn(b"No favorites yet", empty_favorites_page_response.data)

        cleared_overview_response = self.client.get("/")
        self.assertEqual(cleared_overview_response.status_code, 200)
        self.assertNotIn(b"schedule-band schedule-band--active", cleared_overview_response.data)

    def test_attendee_checkin_allows_missing_name_location_and_photos(self):
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Loose Entry",
                "festival_name": "North Field",
                "performance_date": "2026-08-20",
                "start_time": "19:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={},
            follow_redirects=True,
        )
        self.assertEqual(attendee_response.status_code, 200)
        self.assertIn(b"Anonymous", attendee_response.data)
        self.assertIn(b"Not shared", attendee_response.data)
        self.assertIn(b"No POV photo uploaded.", attendee_response.data)
        self.assertIn(b"No side photo uploaded.", attendee_response.data)

        api_response = self.client.get("/api/bands/1/attendees")
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.get_json()
        self.assertEqual(payload["attendees"][0]["display_name"], "Anonymous")
        self.assertIsNone(payload["attendees"][0]["latitude"])
        self.assertIsNone(payload["attendees"][0]["longitude"])
        self.assertIsNone(payload["attendees"][0]["map_x"])
        self.assertIsNone(payload["attendees"][0]["map_y"])
        self.assertIsNone(payload["attendees"][0]["festival_map_pin"])
        self.assertIsNone(payload["attendees"][0]["map_url"])
        self.assertIsNone(payload["attendees"][0]["directions_url"])
        self.assertIsNone(payload["attendees"][0]["ios_app_directions_url"])
        self.assertIsNone(payload["attendees"][0]["pov_image_url"])
        self.assertIsNone(payload["attendees"][0]["side_image_url"])

    def test_check_ins_page_shows_only_last_two_hours(self):
        first_band_response = self.client.post(
            "/bands",
            data={
                "band_name": "Fresh Signal",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-20",
                "start_time": "19:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(first_band_response.status_code, 302)

        second_band_response = self.client.post(
            "/bands",
            data={
                "band_name": "Old Signal",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-20",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(second_band_response.status_code, 302)

        third_band_response = self.client.post(
            "/bands",
            data={
                "band_name": "Ancient Signal",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-20",
                "start_time": "21:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(third_band_response.status_code, 302)

        fresh_check_in_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Mila",
                "map_x": "45.0",
                "map_y": "55.0",
            },
            follow_redirects=False,
        )
        self.assertEqual(fresh_check_in_response.status_code, 302)

        old_check_in_response = self.client.post(
            "/bands/2/attendees",
            data={
                "display_name": "Nina",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "map_x": "35.0",
                "map_y": "65.0",
            },
            follow_redirects=False,
        )
        self.assertEqual(old_check_in_response.status_code, 302)

        ancient_check_in_response = self.client.post(
            "/bands/3/attendees",
            data={
                "display_name": "Noor",
                "map_x": "20.0",
                "map_y": "30.0",
            },
            follow_redirects=False,
        )
        self.assertEqual(ancient_check_in_response.status_code, 302)

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=7)).strftime("%Y-%m-%d %H:%M:%S")
        older_time = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        ancient_time = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        db = sqlite3.connect(self.app.config["DATABASE"])
        db.execute("UPDATE attendees SET created_at = ? WHERE display_name = ?", (recent_time, "Mila"))
        db.execute("UPDATE attendees SET created_at = ? WHERE display_name = ?", (older_time, "Nina"))
        db.execute("UPDATE attendees SET created_at = ? WHERE display_name = ?", (ancient_time, "Noor"))
        db.commit()
        db.close()

        self.client.get("/")
        response = self.client.get("/check-ins")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Check Ins", response.data)
        self.assertIn(b"Last 2 hours", response.data)
        self.assertIn(b"Friend position", response.data)
        self.assertIn(b"GMM 2026 festival map with recent check-in pins", response.data)
        self.assertIn(b"data-map-shared-pin", response.data)
        self.assertIn(b"--pin-x: 45.0%; --pin-y: 55.0%;", response.data)
        self.assertIn(b"--pin-x: 35.0%; --pin-y: 65.0%;", response.data)
        self.assertIn("Mila · 7m".encode(), response.data)
        self.assertIn("Nina · 1h".encode(), response.data)
        self.assertIn(b"Fresh Signal", response.data)
        self.assertIn(b"Mila", response.data)
        self.assertIn(b"Shared on GMM map", response.data)
        self.assertIn(b"Old Signal", response.data)
        self.assertIn(b"Nina", response.data)
        self.assertNotIn(b"Ancient Signal", response.data)
        self.assertNotIn(b"Noor", response.data)

    def test_relative_time_label_for_older_checkins(self):
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Slow Echo",
                "festival_name": "North Field",
                "performance_date": "2026-08-20",
                "start_time": "18:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Ari",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (make_image_upload(), "pov.jpg"),
                "side_image": (make_image_upload(color=(140, 80, 120)), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)

        older_time = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        db = sqlite3.connect(self.app.config["DATABASE"])
        db.execute("UPDATE attendees SET created_at = ? WHERE id = 1", (older_time,))
        db.commit()
        db.close()

        response = self.client.get("/bands/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Checked in 2 hrs ago", response.data)

    def test_delete_stage_removes_all_bands_on_that_lane(self):
        first_band = self.client.post(
            "/bands",
            data={
                "band_name": "North Skyline",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "21:00",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(first_band.status_code, 302)

        second_band = self.client.post(
            "/bands",
            data={
                "band_name": "Midnight Current",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "21:15",
                "end_time": "22:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(second_band.status_code, 302)

        third_band = self.client.post(
            "/bands",
            data={
                "band_name": "Tent Echo",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "20:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(third_band.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Mila",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (make_image_upload(), "pov.jpg"),
                "side_image": (make_image_upload(color=(140, 80, 120)), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)
        self.assertTrue(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertTrue(any(self.upload_root.joinpath("attendees").iterdir()))

        delete_response = self.client.post(
            "/stages/delete",
            data={
                "performance_date": "2026-08-19",
                "festival_name": "North Field",
                "stage_name_value": "Main Stage",
            },
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"Main Stage on 2026-08-19 was deleted from North Field.", delete_response.data)
        self.assertIn(b"Tent Stage", delete_response.data)
        self.assertEqual(self.client.get("/bands/1").status_code, 404)
        self.assertEqual(self.client.get("/bands/2").status_code, 404)
        self.assertEqual(self.client.get("/bands/3").status_code, 200)
        self.assertFalse(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))

    def test_delete_band_removes_band_and_uploaded_files(self):
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Midnight Parade",
                "festival_name": "North Field",
                "stage_name": "Lake Stage",
                "performance_date": "2026-08-21",
                "start_time": "22:00",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Nina",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (make_image_upload(), "pov.jpg"),
                "side_image": (make_image_upload(color=(140, 80, 120)), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)
        self.assertTrue(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertTrue(any(self.upload_root.joinpath("attendees").iterdir()))

        delete_response = self.client.post("/bands/1/delete", follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"Midnight Parade was deleted.", delete_response.data)
        self.assertIn(b"No bands added yet", delete_response.data)
        self.assertFalse(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))
        self.assertEqual(self.client.get("/bands/1").status_code, 404)

    def test_resolve_local_ssl_context_uses_default_dev_cert_paths(self):
        cert_dir = Path(self.temp_dir.name) / "certs"
        cert_dir.mkdir()
        cert_path = cert_dir / "dev-cert.pem"
        key_path = cert_dir / "dev-key.pem"
        cert_path.write_text("cert", encoding="utf-8")
        key_path.write_text("key", encoding="utf-8")

        with patch.dict(os.environ, {"LOCAL_HTTPS": "1"}, clear=False):
            ssl_context = resolve_local_ssl_context(self.temp_dir.name)

        self.assertEqual(ssl_context, (str(cert_path), str(key_path)))

    def test_resolve_local_ssl_context_returns_none_when_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_local_ssl_context(self.temp_dir.name))


if __name__ == "__main__":
    unittest.main()
