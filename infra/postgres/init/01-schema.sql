-- F1 Pit Wall schema. Executed once on first container start.

CREATE TABLE races (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT        NOT NULL,
    circuit      TEXT        NOT NULL,
    season       INT         NOT NULL,
    total_laps   INT         NOT NULL CHECK (total_laps > 0),
    source       TEXT        NOT NULL CHECK (source IN ('SIMULATION', 'REPLAY')),
    status       TEXT        NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'FINISHED', 'ABORTED')),
    winner_code  TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE TABLE race_entries (
    race_id       BIGINT NOT NULL REFERENCES races (id) ON DELETE CASCADE,
    driver_code   TEXT   NOT NULL,
    driver_number INT    NOT NULL,
    full_name     TEXT   NOT NULL,
    team_name     TEXT   NOT NULL,
    team_colour   TEXT   NOT NULL,
    grid_position INT    NOT NULL,
    PRIMARY KEY (race_id, driver_code)
);

CREATE TABLE laps (
    race_id          BIGINT       NOT NULL,
    driver_code      TEXT         NOT NULL,
    lap_number       INT          NOT NULL CHECK (lap_number > 0),
    lap_time_ms      INT          NOT NULL,
    sector1_ms       INT,
    sector2_ms       INT,
    sector3_ms       INT,
    position         INT          NOT NULL,
    gap_to_leader_ms INT          NOT NULL,
    compound         TEXT         NOT NULL,
    tyre_age         INT          NOT NULL,
    tyre_wear        NUMERIC(5, 1) NOT NULL,
    top_speed_kmh    INT,
    recorded_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (race_id, driver_code, lap_number),
    FOREIGN KEY (race_id, driver_code) REFERENCES race_entries (race_id, driver_code) ON DELETE CASCADE
);

CREATE TABLE pit_stops (
    id                 BIGSERIAL PRIMARY KEY,
    race_id            BIGINT      NOT NULL,
    driver_code        TEXT        NOT NULL,
    lap_number         INT         NOT NULL,
    pit_lane_time_ms   INT         NOT NULL,
    stationary_time_ms INT,
    compound_out       TEXT        NOT NULL,
    recorded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (race_id, driver_code) REFERENCES race_entries (race_id, driver_code) ON DELETE CASCADE
);
CREATE INDEX pit_stops_race_idx ON pit_stops (race_id, driver_code);

CREATE TABLE telemetry (
    id           BIGSERIAL PRIMARY KEY,
    race_id      BIGINT      NOT NULL,
    driver_code  TEXT        NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    speed_kmh    INT         NOT NULL,
    rpm          INT         NOT NULL,
    gear         SMALLINT    NOT NULL,
    throttle_pct SMALLINT    NOT NULL,
    tyre_temp_c  NUMERIC(5, 1) NOT NULL,
    fuel_kg      NUMERIC(5, 1) NOT NULL,
    ers_pct      SMALLINT    NOT NULL,
    FOREIGN KEY (race_id, driver_code) REFERENCES race_entries (race_id, driver_code) ON DELETE CASCADE
);
CREATE INDEX telemetry_recorded_at_idx ON telemetry (recorded_at);
CREATE INDEX telemetry_driver_idx ON telemetry (race_id, driver_code, recorded_at DESC);

-- Written by race-control from RabbitMQ events (idempotent by event_id).
CREATE TABLE race_events (
    event_id    UUID PRIMARY KEY,
    race_id     BIGINT      NOT NULL REFERENCES races (id) ON DELETE CASCADE,
    lap_number  INT         NOT NULL,
    event_type  TEXT        NOT NULL,
    driver_code TEXT,
    payload     JSONB       NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX race_events_race_idx ON race_events (race_id, occurred_at DESC);
CREATE INDEX race_events_type_idx ON race_events (event_type);

CREATE TABLE championship_results (
    race_id     BIGINT       NOT NULL REFERENCES races (id) ON DELETE CASCADE,
    driver_code TEXT         NOT NULL,
    team_name   TEXT         NOT NULL,
    position    INT          NOT NULL,
    points      NUMERIC(4, 1) NOT NULL,
    PRIMARY KEY (race_id, driver_code)
);

-- Classification of any race: latest lap of every driver.
CREATE FUNCTION race_standings(p_race_id BIGINT)
RETURNS TABLE (
    "position"    INT,
    driver_code   TEXT,
    full_name     TEXT,
    team_name     TEXT,
    team_colour   TEXT,
    laps          INT,
    gap_s         NUMERIC,
    last_lap_s    NUMERIC,
    compound      TEXT,
    tyre_age      INT,
    tyre_wear     NUMERIC,
    pit_stops     BIGINT
)
LANGUAGE sql STABLE AS $$
    WITH last_laps AS (
        SELECT DISTINCT ON (l.driver_code) l.*
        FROM laps l
        WHERE l.race_id = p_race_id
        ORDER BY l.driver_code, l.lap_number DESC
    )
    SELECT ll.position,
           e.driver_code,
           e.full_name,
           e.team_name,
           e.team_colour,
           ll.lap_number,
           round(ll.gap_to_leader_ms / 1000.0, 3),
           round(ll.lap_time_ms / 1000.0, 3),
           ll.compound,
           ll.tyre_age,
           ll.tyre_wear,
           (SELECT count(*) FROM pit_stops p WHERE p.race_id = ll.race_id AND p.driver_code = ll.driver_code)
    FROM last_laps ll
    JOIN race_entries e USING (race_id, driver_code)
    ORDER BY ll.lap_number DESC, ll.position;
$$;

CREATE VIEW v_live_standings AS
SELECT * FROM race_standings((SELECT max(id) FROM races));

CREATE VIEW v_championship AS
SELECT driver_code,
       (array_agg(team_name ORDER BY race_id DESC))[1] AS team_name,
       sum(points)                                  AS points,
       count(*) FILTER (WHERE position = 1)         AS wins,
       count(*) FILTER (WHERE position <= 3)        AS podiums,
       count(*)                                     AS races
FROM championship_results
GROUP BY driver_code
ORDER BY points DESC, wins DESC;
