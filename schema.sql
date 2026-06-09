CREATE TABLE IF NOT EXISTS bands (
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

CREATE TABLE IF NOT EXISTS attendees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id INTEGER NOT NULL,
    display_name TEXT,
    latitude REAL,
    longitude REAL,
    map_x REAL,
    map_y REAL,
    note TEXT,
    pov_image TEXT,
    side_image TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (band_id) REFERENCES bands (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (band_id) REFERENCES bands (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bands_performance
    ON bands (performance_date, start_time);

CREATE INDEX IF NOT EXISTS idx_attendees_band_id
    ON attendees (band_id);

CREATE INDEX IF NOT EXISTS idx_favorites_band_id
    ON favorites (band_id);
