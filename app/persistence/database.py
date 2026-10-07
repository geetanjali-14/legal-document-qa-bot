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
                # Production PostgreSQL connection pooling
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
            # Safe table creation (does NOT drop existing data)
            from app.persistence import models  # noqa: F401
            Base.metadata.create_all(bind=self.engine)
            logger.info(f"Database initialized safely at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database at {self.db_path}: {str(e)}")
            raise RuntimeError(f"Database initialization failed: {str(e)}") from e

    def get_session(self) -> Session:
        if self.session_factory is None:
            raise RuntimeError("Database session factory is not initialized.")
        return self.session_factory()
