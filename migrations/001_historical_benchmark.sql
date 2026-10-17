-- Historical Benchmark Database — schema and seed data.
--
-- Activated when DATABASE_URL is set; the block falls back to its in-memory
-- file-backed store when this database is unreachable or empty.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS historical_benchmark (
    id SERIAL PRIMARY KEY,
    item_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    avg_cost NUMERIC NOT NULL,
    std_dev NUMERIC NOT NULL DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 1,
    location TEXT,
    source TEXT,                    -- 'RSMeans' | 'Reference Project' | 'Project_X' | etc.
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_name, unit, location)
);

CREATE INDEX IF NOT EXISTS hb_item_name_idx ON historical_benchmark (item_name);
CREATE INDEX IF NOT EXISTS hb_location_idx ON historical_benchmark (location);

-- Location factors (regional cost adjustments).
CREATE TABLE IF NOT EXISTS location_factor (
    location TEXT PRIMARY KEY,
    factor NUMERIC NOT NULL,
    notes TEXT
);

-- Seed location factors. Values mirror the file-backed defaults documented in
-- app/blocks/historical_benchmark.py — when the in-code defaults change, update
-- this seed so a fresh database boots with parity.
INSERT INTO location_factor (location, factor, notes) VALUES
    ('us_national_average', 1.00, 'baseline'),
    ('riyadh',              0.85, 'Saudi Arabia: 15% below US national avg'),
    ('jeddah',              0.83, 'Saudi Arabia coastal'),
    ('dubai',               0.95, 'UAE'),
    ('london',              1.45, 'UK premium market')
ON CONFLICT (location) DO NOTHING;

-- Seed a handful of benchmark rows for tests / first-boot smoke checks.
INSERT INTO historical_benchmark (item_name, unit, avg_cost, std_dev, sample_size, location, source) VALUES
    ('concrete_grade_c30',  'm3', 165.00,  8.50,  120, 'us_national_average', 'RSMeans'),
    ('rebar',               'kg',   1.80,  0.10,  250, 'us_national_average', 'RSMeans'),
    ('formwork',            'm2',  45.00,  4.20,  180, 'us_national_average', 'RSMeans'),
    ('concrete_grade_c30',  'm3', 140.25, 10.00,   45, 'riyadh',              'Reference Project'),
    ('rebar',               'kg',   1.53,  0.15,   60, 'riyadh',              'Reference Project')
ON CONFLICT (item_name, unit, location) DO NOTHING;
