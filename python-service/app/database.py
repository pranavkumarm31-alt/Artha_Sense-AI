import os
import uuid
from pathlib import Path
from datetime import date
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .schemas import IngestRequest, StoredObservation


MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_database_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


def connect() -> psycopg.Connection[Any]:
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5"))
    if timeout < 1:
        raise ValueError("DATABASE_CONNECT_TIMEOUT_SECONDS must be at least one second.")
    return psycopg.connect(database_url, row_factory=dict_row, connect_timeout=timeout)


def migrate() -> list[str]:
    applied: list[str] = []
    with connect() as connection:
        with connection.transaction():
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = migration_path.name
                exists = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
                ).fetchone()
                if exists:
                    continue
                with connection.transaction():
                    connection.execute(migration_path.read_text(encoding="utf-8"))
                    connection.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                    )
                applied.append(version)
    return applied


def ingest(payload: IngestRequest) -> int:
    fetches = {fetch.source_key: fetch for fetch in payload.fetches}
    upserted = 0
    with connect() as connection:
        with connection.cursor() as cursor:
            source_ids: dict[str, int] = {}
            for source_key, fetch in fetches.items():
                source = cursor.execute(
                    """
                    INSERT INTO data_sources (source_key, name, url, dataset, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_key) DO UPDATE
                    SET name = EXCLUDED.name, url = EXCLUDED.url,
                        dataset = EXCLUDED.dataset, updated_at = now()
                    RETURNING id
                    """,
                    (
                        source_key,
                        payload.source_name,
                        payload.source_url,
                        fetch.dataset,
                        Jsonb({"dataset": fetch.dataset}),
                    ),
                ).fetchone()
                source_ids[source_key] = source["id"]

            for failure in payload.failed_sources:
                source = cursor.execute(
                    """
                    INSERT INTO data_sources (source_key, name, url, dataset, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_key) DO UPDATE
                    SET name = EXCLUDED.name, url = EXCLUDED.url,
                        dataset = EXCLUDED.dataset, updated_at = now()
                    RETURNING id
                    """,
                    (
                        failure.source_key,
                        payload.source_name,
                        payload.source_url,
                        failure.dataset,
                        Jsonb({"dataset": failure.dataset}),
                    ),
                ).fetchone()
                cursor.execute(
                    """
                    INSERT INTO data_ingestion_logs
                        (source_id, started_at, completed_at, status, error, details)
                    VALUES (%s, %s, now(), 'failed', %s, %s)
                    """,
                    (
                        source["id"],
                        datetime.now(timezone.utc),
                        failure.error,
                        Jsonb({"dataset": failure.dataset}),
                    ),
                )

            for observation in payload.observations:
                source_id = source_ids[observation.source_key]
                indicator = cursor.execute(
                    """
                    INSERT INTO economic_indicators
                        (metric_code, name, frequency, unit, base_year, source_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (metric_code) DO UPDATE
                    SET name = EXCLUDED.name,
                        frequency = EXCLUDED.frequency,
                        unit = EXCLUDED.unit,
                        base_year = EXCLUDED.base_year,
                        source_id = EXCLUDED.source_id,
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        observation.metric_code,
                        observation.name,
                        observation.frequency,
                        observation.unit,
                        observation.base_year,
                        source_id,
                    ),
                ).fetchone()
                cursor.execute(
                    """
                    INSERT INTO economic_observations
                        (indicator_id, observation_period, observation_start,
                         fiscal_year, quarter, month, value, value_type, unit,
                         base_year, source_id, source_status, last_fetched_at,
                         publication_date, source_metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (indicator_id, observation_period) DO UPDATE
                    SET observation_start = EXCLUDED.observation_start,
                        fiscal_year = EXCLUDED.fiscal_year,
                        quarter = EXCLUDED.quarter,
                        month = EXCLUDED.month,
                        value = EXCLUDED.value,
                        value_type = EXCLUDED.value_type,
                        unit = EXCLUDED.unit,
                        base_year = EXCLUDED.base_year,
                        source_id = EXCLUDED.source_id,
                        source_status = EXCLUDED.source_status,
                        last_fetched_at = EXCLUDED.last_fetched_at,
                        publication_date = EXCLUDED.publication_date,
                        source_metadata = EXCLUDED.source_metadata,
                        updated_at = now()
                    """,
                    (
                        indicator["id"],
                        observation.observation_period,
                        observation.observation_start,
                        observation.fiscal_year,
                        observation.quarter,
                        observation.month,
                        observation.value,
                        observation.value_type,
                        observation.unit,
                        observation.base_year,
                        source_id,
                        observation.source_status,
                        observation.last_fetched_at,
                        observation.publication_date,
                        Jsonb(observation.source_metadata),
                    ),
                )
                upserted += 1

            for source_key, fetch in fetches.items():
                source_id = source_ids[source_key]
                inserted = sum(
                    observation.source_key == source_key for observation in payload.observations
                )
                cursor.execute(
                    """
                    INSERT INTO data_ingestion_logs
                        (source_id, started_at, completed_at, status,
                         observations_read, observations_upserted, details)
                    VALUES (%s, %s, now(), %s, %s, %s, %s)
                    """,
                    (
                        source_id,
                        datetime.now(timezone.utc),
                        "success" if fetch.status == "LIVE" else "partial",
                        fetch.observation_count,
                        inserted,
                        Jsonb(
                            {
                                "dataset": fetch.dataset,
                                "fetch_status": fetch.status,
                                "last_successful_fetch": fetch.last_successful_fetch.isoformat(),
                            }
                        ),
                    ),
                )
    return upserted


def get_history(metric_code: str, limit: int = 1000) -> list[StoredObservation]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT ds.source_key, ds.name AS source_name, ds.url AS source_url,
                   i.metric_code, i.name, i.frequency,
                   o.observation_period, o.observation_start, o.fiscal_year,
                   o.quarter, o.month, o.value, o.value_type, o.unit,
                   o.base_year, o.source_status, o.last_fetched_at
            FROM economic_observations o
            JOIN economic_indicators i ON i.id = o.indicator_id
            JOIN data_sources ds ON ds.id = o.source_id
            WHERE i.metric_code = %s
            ORDER BY o.observation_start ASC
            LIMIT %s
            """,
            (metric_code, limit),
        ).fetchall()
    return [StoredObservation.model_validate(row) for row in rows]


def get_history_range(
    metric_code: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 10000,
) -> list[StoredObservation]:
    clauses = ["i.metric_code = %s"]
    parameters: list[object] = [metric_code]
    if start is not None:
        clauses.append("o.observation_start >= %s")
        parameters.append(start)
    if end is not None:
        clauses.append("o.observation_start <= %s")
        parameters.append(end)
    parameters.append(limit)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT ds.source_key, ds.name AS source_name, ds.url AS source_url,
                   i.metric_code, i.name, i.frequency,
                   o.observation_period, o.observation_start, o.fiscal_year,
                   o.quarter, o.month, o.value, o.value_type, o.unit,
                   o.base_year, o.source_status, o.last_fetched_at
            FROM economic_observations o
            JOIN economic_indicators i ON i.id = o.indicator_id
            JOIN data_sources ds ON ds.id = o.source_id
            WHERE {' AND '.join(clauses)}
            ORDER BY o.observation_start ASC
            LIMIT %s
            """,
            tuple(parameters),
        ).fetchall()
    return [StoredObservation.model_validate(row) for row in rows]


def persist_analysis(
    *,
    analysis_type: str,
    observation_period: str | None,
    content: dict[str, object],
    source_observations: list[dict[str, object]],
    analysis_version: str = "1.0",
) -> int:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO economic_analysis
                    (analysis_type, observation_period, content, source_observations,
                     analysis_version)
                SELECT %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM economic_analysis
                    WHERE analysis_type = %s
                      AND COALESCE(observation_period, '') = COALESCE(%s, '')
                      AND analysis_version = %s
                )
                """,
                (
                    analysis_type,
                    observation_period,
                    Jsonb({**content, "analysis_version": analysis_version}),
                    Jsonb(source_observations),
                    analysis_version,
                    analysis_type,
                    observation_period,
                    analysis_version,
                ),
            )
            return cursor.rowcount


def persist_anomalies(
    anomalies: list[object],
    *,
    indicator_code: str,
    model_parameters: dict[str, object],
) -> int:
    if not anomalies:
        return 0
    persisted = 0
    with connect() as connection:
        with connection.cursor() as cursor:
            indicator = cursor.execute(
                """
                SELECT id, name
                FROM economic_indicators
                WHERE metric_code = %s
                """,
                (indicator_code,),
            ).fetchone()
            if indicator is None:
                return 0
            for anomaly in anomalies:
                cursor.execute(
                    """
                    INSERT INTO anomaly_detections
                        (indicator_id, observation_period, actual_value,
                         expected_value, deviation, anomaly_score, severity,
                         detection_method, explanation, detected_at,
                         percentage_deviation, model_version, model_parameters,
                         source_key, source_name, source_url, source_metadata,
                         analysis_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, '1.0')
                    ON CONFLICT (indicator_id, observation_period, detection_method)
                    DO UPDATE
                    SET actual_value = EXCLUDED.actual_value,
                        expected_value = EXCLUDED.expected_value,
                        deviation = EXCLUDED.deviation,
                        anomaly_score = EXCLUDED.anomaly_score,
                        severity = EXCLUDED.severity,
                        explanation = EXCLUDED.explanation,
                        detected_at = EXCLUDED.detected_at,
                        percentage_deviation = EXCLUDED.percentage_deviation,
                        model_version = EXCLUDED.model_version,
                        model_parameters = EXCLUDED.model_parameters,
                        source_key = EXCLUDED.source_key,
                        source_name = EXCLUDED.source_name,
                        source_url = EXCLUDED.source_url,
                        source_metadata = EXCLUDED.source_metadata
                    """,
                    (
                        indicator["id"],
                        getattr(anomaly, "observation_period"),
                        getattr(anomaly, "actual_value"),
                        getattr(anomaly, "expected_value"),
                        getattr(anomaly, "absolute_deviation"),
                        getattr(anomaly, "anomaly_score"),
                        getattr(anomaly, "severity"),
                        getattr(anomaly, "detection_method"),
                        getattr(anomaly, "explanation"),
                        getattr(anomaly, "detected_at"),
                        getattr(anomaly, "percentage_deviation"),
                        getattr(anomaly, "model_version"),
                        Jsonb(model_parameters),
                        getattr(anomaly, "source_key"),
                        getattr(anomaly, "source_name"),
                        getattr(anomaly, "source_url"),
                        Jsonb(
                            {
                                "observation_start": getattr(anomaly, "observation_start").isoformat(),
                                "observation_period": getattr(anomaly, "observation_period"),
                            }
                        ),
                    ),
                )
                persisted += 1
    return persisted


def get_anomalies(
    *,
    indicator_code: str | None = None,
    severity: str | None = None,
    method: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if indicator_code:
        clauses.append("i.metric_code = %s")
        parameters.append(indicator_code)
    if severity:
        clauses.append("a.severity = %s")
        parameters.append(severity)
    if method:
        clauses.append("a.detection_method = %s")
        parameters.append(method)
    if start:
        clauses.append("COALESCE(a.source_metadata->>'observation_start', '') >= %s")
        parameters.append(start.isoformat())
    if end:
        clauses.append("COALESCE(a.source_metadata->>'observation_start', '') <= %s")
        parameters.append(end.isoformat())
    parameters.append(limit)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT i.metric_code AS indicator_code, i.name AS indicator_name,
                   a.observation_period, a.source_metadata->>'observation_start' AS observation_start,
                   a.actual_value, a.expected_value, a.deviation AS absolute_deviation,
                   a.percentage_deviation, a.anomaly_score, a.detection_method,
                   a.severity, a.detected_at, a.source_key, a.source_name,
                   a.source_url, a.model_version, a.model_parameters, a.explanation
            FROM anomaly_detections a
            JOIN economic_indicators i ON i.id = a.indicator_id
            {where}
            ORDER BY a.detected_at DESC, a.observation_period DESC
            LIMIT %s
            """,
            tuple(parameters),
        ).fetchall()
    return [dict(row) for row in rows]


def get_anomaly_summary() -> dict[str, object]:
    with connect() as connection:
        total = connection.execute("SELECT count(*) AS count FROM anomaly_detections").fetchone()["count"]
        levels = connection.execute(
            """
            SELECT severity, count(*) AS count
            FROM anomaly_detections
            GROUP BY severity
            """
        ).fetchall()
        indicators = connection.execute(
            """
            SELECT i.metric_code, count(*) AS count
            FROM anomaly_detections a
            JOIN economic_indicators i ON i.id = a.indicator_id
            GROUP BY i.metric_code
            """
        ).fetchall()
    return {
        "total": total,
        "low": next((row["count"] for row in levels if row["severity"] == "low"), 0),
        "medium": next((row["count"] for row in levels if row["severity"] == "medium"), 0),
        "high": next((row["count"] for row in levels if row["severity"] == "high"), 0),
        "by_indicator": {row["metric_code"]: row["count"] for row in indicators},
    }


def persist_forecast(
    *,
    indicator_code: str,
    model_name: str,
    model_version: str,
    status: str,
    warning: str | None,
    training_period_start: date | None,
    training_period_end: date | None,
    observations_used: int,
    metrics: object | None,
    forecasts: list[object],
) -> bool:
    with connect() as connection:
        with connection.cursor() as cursor:
            indicator = cursor.execute(
                """
                SELECT i.id, i.name, i.unit
                FROM economic_indicators i
                WHERE i.metric_code = %s
                """,
                (indicator_code,),
            ).fetchone()
            if indicator is None:
                return False

            model = cursor.execute(
                """
                INSERT INTO model_registry
                    (model_key, model_name, version, algorithm, status)
                VALUES (%s, %s, %s, %s, 'candidate')
                ON CONFLICT (model_key) DO UPDATE
                SET model_name = EXCLUDED.model_name,
                    version = EXCLUDED.version,
                    algorithm = EXCLUDED.algorithm,
                    status = CASE
                        WHEN model_registry.status = 'failed' THEN 'candidate'
                        ELSE model_registry.status
                    END,
                    updated_at = now()
                RETURNING id
                """,
                (
                    f"{indicator_code}:{model_name}",
                    model_name,
                    model_version,
                    model_name,
                ),
            ).fetchone()

            training = cursor.execute(
                """
                INSERT INTO model_training_runs
                    (model_id, indicator_id, started_at, completed_at, status,
                     observations_used, training_period_start, training_period_end,
                     validation_method, warnings, error)
                VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    model["id"],
                    indicator["id"],
                    datetime.now(timezone.utc),
                    "success" if status == "success" else status,
                    observations_used,
                    training_period_start,
                    training_period_end,
                    "rolling-origin walk-forward, one-step retraining",
                    Jsonb([] if warning is None else [warning]),
                    warning if status != "success" else None,
                ),
            ).fetchone()

            if metrics is not None:
                metric_values = [
                    ("MAE", getattr(metrics, "mae", None)),
                    ("RMSE", getattr(metrics, "rmse", None)),
                    ("sMAPE", getattr(metrics, "smape", None)),
                    ("directional_accuracy", getattr(metrics, "directional_accuracy", None)),
                ]
                for metric_name, metric_value in metric_values:
                    cursor.execute(
                        """
                        INSERT INTO forecast_metrics
                            (training_run_id, model_id, indicator_id, metric_name,
                             metric_value, test_period_start, test_period_end,
                             test_observations, baseline_model, baseline_value)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
                        ON CONFLICT (training_run_id, metric_name) DO UPDATE
                        SET metric_value = EXCLUDED.metric_value,
                            test_period_start = EXCLUDED.test_period_start,
                            test_period_end = EXCLUDED.test_period_end,
                            test_observations = EXCLUDED.test_observations
                        """,
                        (
                            training["id"],
                            model["id"],
                            indicator["id"],
                            metric_name,
                            metric_value,
                            getattr(metrics, "test_period_start", None),
                            getattr(metrics, "test_period_end", None),
                            getattr(metrics, "test_observations", 0),
                        ),
                    )

            for point in forecasts:
                cursor.execute(
                    """
                    INSERT INTO forecasts
                        (indicator_id, model_id, training_run_id, observation_period,
                         observation_start, horizon, value, lower_bound, upper_bound,
                         unit, generated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (indicator_id, model_id, observation_period)
                    DO UPDATE
                    SET training_run_id = EXCLUDED.training_run_id,
                        horizon = EXCLUDED.horizon,
                        value = EXCLUDED.value,
                        lower_bound = EXCLUDED.lower_bound,
                        upper_bound = EXCLUDED.upper_bound,
                        unit = EXCLUDED.unit,
                        generated_at = now()
                    """,
                    (
                        indicator["id"],
                        model["id"],
                        training["id"],
                        getattr(point, "observation_period"),
                        getattr(point, "observation_start"),
                        getattr(point, "horizon"),
                        getattr(point, "value"),
                        getattr(point, "lower_bound"),
                        getattr(point, "upper_bound"),
                        indicator["unit"],
                    ),
                )
    return True


def get_saved_forecasts(
    indicator_code: str,
    model_name: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    with connect() as connection:
        if model_name:
            rows = connection.execute(
                """
                SELECT i.metric_code AS indicator_code, mr.model_name AS model,
                       mr.version AS model_version, f.observation_period,
                       f.observation_start, f.horizon, f.value, f.lower_bound,
                       f.upper_bound, f.unit, f.generated_at,
                       tr.training_period_start, tr.training_period_end
                FROM forecasts f
                JOIN economic_indicators i ON i.id = f.indicator_id
                JOIN model_registry mr ON mr.id = f.model_id
                JOIN model_training_runs tr ON tr.id = f.training_run_id
                WHERE i.metric_code = %s AND mr.model_name = %s
                ORDER BY f.observation_start ASC
                LIMIT %s
                """,
                (indicator_code, model_name, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT i.metric_code AS indicator_code, mr.model_name AS model,
                       mr.version AS model_version, f.observation_period,
                       f.observation_start, f.horizon, f.value, f.lower_bound,
                       f.upper_bound, f.unit, f.generated_at,
                       tr.training_period_start, tr.training_period_end
                FROM forecasts f
                JOIN economic_indicators i ON i.id = f.indicator_id
                JOIN model_registry mr ON mr.id = f.model_id
                JOIN model_training_runs tr ON tr.id = f.training_run_id
                WHERE i.metric_code = %s
                ORDER BY f.observation_start ASC
                LIMIT %s
                """,
                (indicator_code, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def get_model_comparison(indicator_code: str) -> list[dict[str, object]]:
    with connect() as connection:
        rows = connection.execute(
            """
            WITH ranked_runs AS (
                SELECT tr.id AS training_run_id, tr.model_id, tr.status,
                       tr.completed_at, tr.observations_used,
                       tr.training_period_start, tr.training_period_end,
                       row_number() OVER (
                           PARTITION BY tr.model_id
                           ORDER BY tr.completed_at DESC NULLS LAST
                       ) AS row_rank
                FROM model_training_runs tr
                JOIN economic_indicators i ON i.id = tr.indicator_id
                WHERE i.metric_code = %s
            )
            SELECT mr.model_name AS model, mr.version AS model_version,
                   rr.status, rr.observations_used,
                   rr.training_period_start, rr.training_period_end,
                   jsonb_object_agg(fm.metric_name, fm.metric_value)
                       FILTER (WHERE fm.metric_name IS NOT NULL) AS metrics
            FROM ranked_runs rr
            JOIN model_registry mr ON mr.id = rr.model_id
            LEFT JOIN forecast_metrics fm ON fm.training_run_id = rr.training_run_id
            WHERE rr.row_rank = 1
            GROUP BY mr.model_name, mr.version, rr.status, rr.observations_used,
                     rr.training_period_start, rr.training_period_end
            ORDER BY mr.model_name
            """,
            (indicator_code,),
        ).fetchall()
    return [dict(row) for row in rows]


def persist_research_document(
    *,
    document_id: uuid.UUID,
    title: str,
    source_name: str,
    source_url: str,
    publication_date: date | None,
    version: str,
    content_sha256: str,
    content_type: str,
    metadata: dict[str, object],
    chunks: list[str],
    embeddings: list[list[float]],
) -> tuple[dict[str, object], bool]:
    if len(chunks) != len(embeddings):
        raise ValueError("Each document chunk must have one embedding.")
    with connect() as connection:
        with connection.cursor() as cursor:
            row = cursor.execute(
                """
                INSERT INTO research_documents
                    (id, title, source_name, source_url, publication_date, version,
                     content_sha256, content_type, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_sha256, version) DO NOTHING
                RETURNING id, title, source_name, source_url, publication_date,
                          version, content_sha256, created_at
                """,
                (
                    document_id,
                    title,
                    source_name,
                    source_url,
                    publication_date,
                    version,
                    content_sha256,
                    content_type,
                    Jsonb(metadata),
                ),
            ).fetchone()
            if row is None:
                row = cursor.execute(
                    """
                    SELECT id, title, source_name, source_url, publication_date,
                           version, content_sha256, created_at
                    FROM research_documents
                    WHERE content_sha256 = %s AND version = %s
                    """,
                    (content_sha256, version),
                ).fetchone()
                if row is None:
                    raise RuntimeError("The existing document version could not be loaded.")
                return dict(row), False

            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                cursor.execute(
                    """
                    INSERT INTO research_document_chunks
                        (document_id, chunk_index, content, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        document_id,
                        index,
                        chunk,
                        Jsonb(embedding),
                        Jsonb(metadata),
                    ),
                )
    return dict(row), True


def search_research_chunks(
    *,
    indicator_code: str | None = None,
    source: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if indicator_code:
        clauses.append("(c.metadata->>'indicator_code' = %s OR c.metadata->>'indicator_code' IS NULL)")
        parameters.append(indicator_code)
    if source:
        clauses.append("(d.source_name ILIKE %s OR d.source_url ILIKE %s)")
        parameters.extend((f"%{source}%", f"%{source}%"))
    if start:
        clauses.append("d.publication_date >= %s")
        parameters.append(start)
    if end:
        clauses.append("d.publication_date <= %s")
        parameters.append(end)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT d.id AS document_id, d.title, d.source_name, d.source_url,
                   d.publication_date, d.version, c.chunk_index, c.content,
                   c.embedding, c.metadata
            FROM research_document_chunks c
            JOIN research_documents d ON d.id = c.document_id
            {where}
            ORDER BY d.publication_date DESC NULLS LAST, d.created_at DESC
            LIMIT 5000
            """,
            tuple(parameters),
        ).fetchall()
    return [dict(row) for row in rows]


def list_research_documents(limit: int = 100) -> list[dict[str, object]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, source_name, source_url, publication_date,
                   version, content_sha256, created_at
            FROM research_documents
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_research_sources() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT ds.name AS source_name, ds.url AS source_url,
                   max(o.observation_start) AS latest_observation,
                   NULL::date AS publication_date, 'economic_data'::text AS source_type
            FROM data_sources ds
            JOIN economic_observations o ON o.source_id = ds.id
            GROUP BY ds.id, ds.name, ds.url
            UNION ALL
            SELECT DISTINCT source_name, source_url, NULL::date, publication_date,
                   'document'::text AS source_type
            FROM research_documents
            ORDER BY source_name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_structured_research_evidence(
    *,
    indicator_code: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    clauses = [
        "(%s::text IS NULL OR i.metric_code = %s)",
        "(%s::date IS NULL OR o.observation_start >= %s)",
        "(%s::date IS NULL OR o.observation_start <= %s)",
    ]
    params: tuple[object, ...] = (indicator_code, indicator_code, start, start, end, end)
    with connect() as connection:
        observations = connection.execute(
            f"""
            WITH ranked_observations AS (
            SELECT i.metric_code, i.name, i.frequency, i.unit, i.base_year,
                   o.observation_period, o.observation_start, o.publication_date,
                   o.value, o.value_type,
                   o.source_status, o.last_fetched_at, ds.name AS source_name,
                   ds.url AS source_url, ds.source_key,
                   row_number() OVER (
                       PARTITION BY i.metric_code ORDER BY o.observation_start DESC
                   ) AS period_rank
            FROM economic_observations o
            JOIN economic_indicators i ON i.id = o.indicator_id
            JOIN data_sources ds ON ds.id = o.source_id
            WHERE {' AND '.join(clauses)}
            )
            SELECT * FROM ranked_observations
            WHERE period_rank <= 20
            ORDER BY observation_start DESC
            LIMIT 100
            """,
            params,
        ).fetchall()

        forecast_indicator = indicator_code
        forecasts = connection.execute(
            """
            SELECT i.metric_code, i.name, i.unit, f.observation_period,
                   f.observation_start, f.value, f.lower_bound, f.upper_bound,
                   f.horizon, f.generated_at, mr.model_name, mr.version,
                   tr.training_period_end
            FROM forecasts f
            JOIN economic_indicators i ON i.id = f.indicator_id
            JOIN model_registry mr ON mr.id = f.model_id
            JOIN model_training_runs tr ON tr.id = f.training_run_id
            WHERE (%s::text IS NULL OR i.metric_code = %s)
              AND (%s::date IS NULL OR f.observation_start >= %s)
              AND (%s::date IS NULL OR f.observation_start <= %s)
            ORDER BY f.generated_at DESC, f.observation_start ASC
            LIMIT 40
            """,
            (forecast_indicator, forecast_indicator, start, start, end, end),
        ).fetchall()
        forecast_metrics = connection.execute(
            """
            SELECT tr.id AS training_run_id, i.metric_code, i.name, mr.model_name, mr.version,
                   tr.observations_used, tr.training_period_start, tr.training_period_end,
                   tr.validation_method, tr.completed_at,
                   jsonb_object_agg(fm.metric_name, fm.metric_value)
                       FILTER (WHERE fm.metric_name IS NOT NULL) AS metrics
            FROM model_training_runs tr
            JOIN economic_indicators i ON i.id = tr.indicator_id
            JOIN model_registry mr ON mr.id = tr.model_id
            LEFT JOIN forecast_metrics fm ON fm.training_run_id = tr.id
            WHERE (%s::text IS NULL OR i.metric_code = %s)
              AND (%s::date IS NULL OR tr.training_period_end >= %s)
              AND (%s::date IS NULL OR tr.training_period_end <= %s)
            GROUP BY tr.id, i.metric_code, i.name, mr.model_name, mr.version
            ORDER BY tr.completed_at DESC NULLS LAST
            LIMIT 20
            """,
            (forecast_indicator, forecast_indicator, start, start, end, end),
        ).fetchall()
        analyses = connection.execute(
            """
            SELECT analysis_type, observation_period, content, source_observations,
                   analysis_version, created_at
            FROM economic_analysis
            WHERE (%s::text IS NULL OR content::text ILIKE %s OR source_observations::text ILIKE %s)
              AND (%s::date IS NULL OR created_at::date >= %s)
              AND (%s::date IS NULL OR created_at::date <= %s)
            ORDER BY created_at DESC LIMIT 20
            """,
            (
                indicator_code,
                f"%{indicator_code}%" if indicator_code else None,
                f"%{indicator_code}%" if indicator_code else None,
                start,
                start,
                end,
                end,
            ),
        ).fetchall()
        anomalies = connection.execute(
            """
            SELECT i.metric_code, i.name, i.unit, a.observation_period,
                   a.actual_value, a.expected_value, a.deviation, a.anomaly_score,
                   a.severity, a.detection_method, a.explanation, a.detected_at,
                   a.source_key, a.source_name, a.source_url, a.source_metadata,
                   a.model_version
            FROM anomaly_detections a
            JOIN economic_indicators i ON i.id = a.indicator_id
            WHERE (%s::text IS NULL OR i.metric_code = %s)
              AND (%s::text IS NULL OR COALESCE(a.source_metadata->>'observation_start', '') >= %s)
              AND (%s::text IS NULL OR COALESCE(a.source_metadata->>'observation_start', '') <= %s)
            ORDER BY a.detected_at DESC LIMIT 30
            """,
            (indicator_code, indicator_code, start, start.isoformat() if start else None,
             end, end.isoformat() if end else None),
        ).fetchall()

    evidence: list[dict[str, Any]] = []
    for row in observations:
        evidence.append({
            "id": f"obs:{row['metric_code']}:{row['observation_period']}",
            "kind": "observation",
            "title": f"{row['name']} — {row['observation_period']}",
            "content": (
                f"Observed value: {row['value']} {row['unit']}; type: {row['value_type']}; "
                f"frequency: {row['frequency']}; base year: {row['base_year'] or 'not specified'}; "
                f"status: {row['source_status']}; fetched: {row['last_fetched_at']}."
            ),
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "observation_period": row["observation_period"],
            "publication_date": row["publication_date"],
            "metadata": {"indicator_code": row["metric_code"], "value": float(row["value"]),
                         "unit": row["unit"], "frequency": row["frequency"],
                         "source_key": row["source_key"], "last_fetched_at": row["last_fetched_at"].isoformat()},
        })
    for row in forecasts:
        evidence.append({
            "id": f"forecast:{row['metric_code']}:{row['model_name']}:{row['observation_period']}",
            "kind": "forecast",
            "title": f"{row['name']} forecast — {row['observation_period']}",
            "content": (
                f"Forecast value: {row['value']} {row['unit']} from {row['model_name']} "
                f"version {row['version']}; horizon {row['horizon']}; interval "
                f"{row['lower_bound']} to {row['upper_bound']}; generated {row['generated_at']}; "
                f"training ended {row['training_period_end']}."
            ),
            "source_name": "ArthaSense persisted forecast",
            "source_url": "",
            "observation_period": row["observation_period"],
            "publication_date": None,
            "metadata": {"indicator_code": row["metric_code"], "model": row["model_name"],
                         "model_version": row["version"], "value": float(row["value"]),
                         "unit": row["unit"], "generated_at": row["generated_at"].isoformat()},
        })
    for row in forecast_metrics:
        evidence.append({
            "id": f"forecast-metrics:{row['metric_code']}:{row['model_name']}:{row['completed_at']}",
            "kind": "forecast",
            "title": f"{row['name']} forecast model evaluation — {row['model_name']}",
            "content": (
                f"Persisted evaluation metrics: {row['metrics']}; model {row['model_name']} "
                f"version {row['version']}; observations used {row['observations_used']}; "
                f"training period {row['training_period_start']} to {row['training_period_end']}; "
                f"validation method {row['validation_method']}; completed {row['completed_at']}."
            ),
            "source_name": "ArthaSense persisted forecast evaluation",
            "source_url": "",
            "observation_period": None,
            "publication_date": None,
            "metadata": {
                "indicator_code": row["metric_code"],
                "model": row["model_name"],
                "model_version": row["version"],
                "metrics": row["metrics"],
                "observations_used": row["observations_used"],
                "training_run_id": row["training_run_id"],
                "training_period_start": row["training_period_start"],
                "training_period_end": row["training_period_end"],
            },
        })
    for row in analyses:
        evidence.append({
            "id": f"analysis:{row['analysis_type']}:{row['observation_period'] or row['created_at'].isoformat()}",
            "kind": "analysis",
            "title": f"Persisted {row['analysis_type']} analysis",
            "content": f"Period: {row['observation_period']}; result: {row['content']}; source observations: {row['source_observations']}.",
            "source_name": "ArthaSense persisted analysis",
            "source_url": "",
            "observation_period": row["observation_period"],
            "publication_date": None,
            "metadata": {
                "analysis_type": row["analysis_type"],
                "created_at": row["created_at"].isoformat(),
                "analysis_version": row["analysis_version"],
                "source_observations": row["source_observations"],
            },
        })
    for row in anomalies:
        evidence.append({
            "id": f"anomaly:{row['metric_code']}:{row['observation_period']}:{row['detection_method']}",
            "kind": "anomaly",
            "title": f"{row['name']} statistical anomaly — {row['observation_period']}",
            "content": (
                f"Observed {row['actual_value']} {row['unit']} versus baseline {row['expected_value']}; "
                f"deviation {row['deviation']}; score {row['anomaly_score']}; severity {row['severity']}; "
                f"method {row['detection_method']}; explanation: {row['explanation']}. "
                "This is a statistical anomaly, not evidence of an external cause."
            ),
            "source_name": row["source_name"] or "ArthaSense anomaly analysis",
            "source_url": row["source_url"] or "",
            "observation_period": row["observation_period"],
            "metadata": {
                "indicator_code": row["metric_code"],
                "severity": row["severity"],
                "detection_method": row["detection_method"],
                "source_key": row["source_key"],
                "source_metadata": row["source_metadata"],
                "model_version": row["model_version"],
                "input_observation_ids": [
                    f"obs:{row['metric_code']}:{row['observation_period']}"
                ],
            },
        })
    return evidence


def create_research_conversation(owner_id: uuid.UUID, title: str) -> dict[str, object]:
    conversation_id = uuid.uuid4()
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO research_conversations (id, owner_id, title)
            VALUES (%s, %s, %s)
            RETURNING id, title, created_at, updated_at
            """,
            (conversation_id, owner_id, title[:120]),
        ).fetchone()
    return dict(row)


def conversation_belongs_to(conversation_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
    with connect() as connection:
        return connection.execute(
            "SELECT 1 FROM research_conversations WHERE id = %s AND owner_id = %s",
            (conversation_id, owner_id),
        ).fetchone() is not None


def add_research_message(
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    citations: list[dict[str, object]] | None = None,
) -> None:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO research_messages (conversation_id, role, content, citations)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, role, content, Jsonb(citations or [])),
            )
            cursor.execute(
                "UPDATE research_conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )


def persist_research_exchange(
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    answer: str,
    citations: list[dict[str, object]],
) -> uuid.UUID:
    active_id = conversation_id or uuid.uuid4()
    with connect() as connection:
        with connection.cursor() as cursor:
            if conversation_id is None:
                cursor.execute(
                    """
                    INSERT INTO research_conversations (id, owner_id, title)
                    VALUES (%s, %s, %s)
                    """,
                    (active_id, owner_id, question[:120]),
                )
            else:
                owns_conversation = cursor.execute(
                    """
                    SELECT 1 FROM research_conversations
                    WHERE id = %s AND owner_id = %s
                    FOR UPDATE
                    """,
                    (active_id, owner_id),
                ).fetchone()
                if owns_conversation is None:
                    raise PermissionError("Conversation not found.")
            cursor.execute(
                """
                INSERT INTO research_messages (conversation_id, role, content)
                VALUES (%s, 'user', %s)
                """,
                (active_id, question),
            )
            cursor.execute(
                """
                INSERT INTO research_messages (conversation_id, role, content, citations)
                VALUES (%s, 'assistant', %s, %s)
                """,
                (active_id, answer, Jsonb(citations)),
            )
            cursor.execute(
                "UPDATE research_conversations SET updated_at = now() WHERE id = %s",
                (active_id,),
            )
    return active_id


def get_research_conversations(owner_id: uuid.UUID, limit: int = 30) -> list[dict[str, object]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COALESCE(
                     jsonb_agg(jsonb_build_object(
                       'role', m.role, 'content', m.content, 'citations', m.citations,
                       'created_at', m.created_at
                     ) ORDER BY m.id) FILTER (WHERE m.id IS NOT NULL),
                     '[]'::jsonb
                   ) AS messages
            FROM research_conversations c
            LEFT JOIN research_messages m ON m.conversation_id = c.id
            WHERE c.owner_id = %s
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT %s
            """,
            (owner_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_research_conversation_history(
    conversation_id: uuid.UUID, owner_id: uuid.UUID, limit: int = 8
) -> list[dict[str, str]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT m.role, m.content
            FROM research_messages m
            JOIN research_conversations c ON c.id = m.conversation_id
            WHERE c.id = %s AND c.owner_id = %s
            ORDER BY m.id DESC
            LIMIT %s
            """,
            (conversation_id, owner_id, limit),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
