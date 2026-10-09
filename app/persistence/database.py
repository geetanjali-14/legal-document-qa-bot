from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logging import logger

Base = declarative_base()


class DatabaseManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else settings.DATABASE_PATH
        self.engine = None
        self.session_factory = None
        self._initialize()

    def _initialize(self) -> None:
        try:
            if settings.DATABASE_URL:
                db_url = settings.DATABASE_URL
                if db_url.startswith("postgres://"):
                    db_url = "postgresql://" + db_url[len("postgres://"):]
                is_sqlite = db_url.startswith("sqlite")
            else:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                db_url = f"sqlite:///{self.db_path.resolve()}"
                is_sqlite = True

            if is_sqlite:
                self.engine = create_engine(
                    db_url,
                    connect_args={"check_same_thread": False},
                    pool_pre_ping=True
                )
                with self.engine.connect() as conn:
                    conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                    conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
            else:
                # Production PostgreSQL connection pooling (Neon / standard Postgres)
                self.engine = create_engine(
                    db_url,
                    pool_pre_ping=True,
                    pool_size=10,
                    max_overflow=20
                )

            self.session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            # Ensure vector extension exists on PostgreSQL before table creation
            if not is_sqlite:
                try:
                    with self.engine.begin() as conn:
                        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector;")
                except Exception as ext_err:
                    logger.warning(f"Could not ensure vector extension: {ext_err}")

            # Safe table creation (does NOT drop existing data)
            from app.persistence import models  # noqa: F401
            Base.metadata.create_all(bind=self.engine)

            # Defensive migration: Ensure session_id column exists on existing databases
            try:
                with self.engine.begin() as conn:
                    if is_sqlite:
                        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversations);").fetchall()]
                        if "session_id" not in cols:
                            conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN session_id VARCHAR(64);")
                            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_conversations_session_id ON conversations(session_id);")
                            logger.info("Migrated conversations table (SQLite): added session_id column.")
                    else:
                        # PostgreSQL migration
                        col_exists = conn.exec_driver_sql(
                            "SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'session_id';"
                        ).scalar()
                        if not col_exists:
                            conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN session_id VARCHAR(64);")
                            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_conversations_session_id ON conversations(session_id);")
                            logger.info("Migrated conversations table (PostgreSQL): added session_id column.")
            except Exception as mig_err:
                logger.warning(f"Session column migration check skipped/warning: {mig_err}")

            if is_sqlite:
                logger.info(f"Database initialized safely at {self.db_path}")
            else:
                # Mask credentials if we want to log the host, or just log a safe string
                logger.info("Database initialized safely using DATABASE_URL (PostgreSQL)")
        except Exception as e:
            logger.error(f"Failed to initialize database at {self.db_path}: {str(e)}")
            raise RuntimeError(f"Database initialization failed: {str(e)}") from e

    def get_session(self) -> Session:
        if self.session_factory is None:
            raise RuntimeError("Database session factory is not initialized.")
        return self.session_factory()
