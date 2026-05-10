"""Tests for ReflectionStore."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from atman.reflection.models import ReflectionEvent, ReflectionLevel


class TestReflectionStore:
    """Tests for ReflectionStore."""

    @patch("atman.reflection.store.psycopg")
    def test_init_with_db_url(self, mock_psycopg: Mock) -> None:
        """Test initialization with explicit database URL."""
        from atman.reflection.store import ReflectionStore

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        assert store.db_url == "postgresql://test:pass@localhost/db"
        assert store._conn is None

    @patch.dict("os.environ", {"ATMAN_DB_URL": "postgresql://env:pass@localhost/db"})
    @patch("atman.reflection.store.psycopg")
    def test_init_with_env_var(self, mock_psycopg: Mock) -> None:
        """Test initialization with database URL from environment."""
        from atman.reflection.store import ReflectionStore

        store = ReflectionStore()
        assert store.db_url == "postgresql://env:pass@localhost/db"

    @patch("atman.reflection.store.psycopg", None)
    def test_init_without_psycopg_raises_error(self) -> None:
        """Test that initialization fails without psycopg."""
        from atman.reflection.store import ReflectionStore

        with pytest.raises(ImportError, match="psycopg is required"):
            ReflectionStore()

    @patch("atman.reflection.store.psycopg")
    def test_connect(self, mock_psycopg: Mock) -> None:
        """Test database connection."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store.connect()

        mock_psycopg.connect.assert_called_once_with("postgresql://test:pass@localhost/db")
        assert store._conn == mock_conn

    @patch("atman.reflection.store.psycopg")
    def test_connect_when_already_connected(self, mock_psycopg: Mock) -> None:
        """Test that connect doesn't reconnect if already connected."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.connect()

        # Should not call connect again
        mock_psycopg.connect.assert_not_called()

    @patch("atman.reflection.store.psycopg")
    def test_close(self, mock_psycopg: Mock) -> None:
        """Test closing database connection."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.close()

        mock_conn.close.assert_called_once()
        assert store._closed is True

    @patch("atman.reflection.store.psycopg")
    def test_context_manager(self, mock_psycopg: Mock) -> None:
        """Test using store as context manager."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_psycopg.connect.return_value = mock_conn

        with ReflectionStore(db_url="postgresql://test:pass@localhost/db") as store:
            assert store._conn == mock_conn

        mock_conn.close.assert_called_once()

    @patch("atman.reflection.store.psycopg")
    def test_add_reflection(self, mock_psycopg: Mock) -> None:
        """Test adding a reflection event."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (123,)
        mock_psycopg.connect.return_value = mock_conn

        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Test reflection content",
        )

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        stored = store.add(event)

        assert stored.id == 123
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("atman.reflection.store.psycopg")
    def test_add_reflection_without_connection_raises_error(self, mock_psycopg: Mock) -> None:
        """Test that add raises error without connection."""
        from atman.reflection.store import ReflectionStore

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")

        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Test reflection content",
        )

        with pytest.raises(RuntimeError, match="Database connection not established"):
            store.add(event)

    @patch("atman.reflection.store.psycopg")
    def test_get_reflection(self, mock_psycopg: Mock) -> None:
        """Test getting a reflection by ID."""
        from atman.reflection.store import ReflectionStore

        agent_id = uuid4()
        expected_event = ReflectionEvent(
            id=123,
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Test reflection content",
        )

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.row_factory = lambda cls: lambda row: expected_event
        mock_cursor.fetchone.return_value = expected_event
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.get(123)

        assert result == expected_event
        mock_cursor.execute.assert_called_once()

    @patch("atman.reflection.store.psycopg")
    def test_get_reflection_not_found(self, mock_psycopg: Mock) -> None:
        """Test getting a non-existent reflection returns None."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.get(999)

        assert result is None

    @patch("atman.reflection.store.psycopg")
    def test_list_by_session(self, mock_psycopg: Mock) -> None:
        """Test listing reflections by session."""
        from atman.reflection.store import ReflectionStore

        agent_id = uuid4()
        session_id = uuid4()
        events = [
            ReflectionEvent(
                id=1,
                agent_id=agent_id,
                level=ReflectionLevel.MICRO,
                session_id=session_id,
                content="Reflection 1",
            ),
            ReflectionEvent(
                id=2,
                agent_id=agent_id,
                level=ReflectionLevel.MICRO,
                session_id=session_id,
                content="Reflection 2",
            ),
        ]

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = events
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.list_by_session(session_id)

        assert len(result) == 2
        assert result == events

    @patch("atman.reflection.store.psycopg")
    def test_list_recent(self, mock_psycopg: Mock) -> None:
        """Test listing recent reflections for an agent."""
        from atman.reflection.store import ReflectionStore

        agent_id = uuid4()
        events = [
            ReflectionEvent(
                id=1,
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="Reflection 1",
            ),
            ReflectionEvent(
                id=2,
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="Reflection 2",
            ),
        ]

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = events
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.list_recent(agent_id, limit=10)

        assert len(result) == 2
        assert result == events

    @patch("atman.reflection.store.psycopg")
    def test_list_by_level(self, mock_psycopg: Mock) -> None:
        """Test listing reflections by level."""
        from atman.reflection.store import ReflectionStore

        agent_id = uuid4()
        events = [
            ReflectionEvent(
                id=1,
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="Daily reflection 1",
            ),
            ReflectionEvent(
                id=2,
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="Daily reflection 2",
            ),
        ]

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = events
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.list_by_level(agent_id, ReflectionLevel.DAILY)

        assert len(result) == 2
        assert result == events

    @patch("atman.reflection.store.psycopg")
    def test_list_by_level_with_since(self, mock_psycopg: Mock) -> None:
        """Test listing reflections by level with time filter."""
        from atman.reflection.store import ReflectionStore

        agent_id = uuid4()
        since = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        events = [
            ReflectionEvent(
                id=1,
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="Daily reflection 1",
            ),
        ]

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = events
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        result = store.list_by_level(agent_id, ReflectionLevel.DAILY, since=since)

        assert len(result) == 1
        # Verify the query includes the since parameter
        assert mock_cursor.execute.called
        call_args = mock_cursor.execute.call_args[0]
        assert since in call_args[1]  # since should be in the query parameters


class TestReflectionStoreDevinReviewFixes:
    """Regression tests for Devin Review issues on PR #414."""

    @patch("atman.reflection.store.psycopg")
    def test_add_wraps_metadata_with_jsonb_adapter(self, mock_psycopg: Mock) -> None:
        """``ReflectionStore.add`` wraps ``metadata`` in :class:`psycopg.types.json.Jsonb`.

        Without the explicit Jsonb wrapper, psycopg cannot serialize a Python
        ``dict`` into the ``metadata jsonb`` column and the INSERT fails at
        runtime.
        """
        from psycopg.types.json import Jsonb

        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_psycopg.connect.return_value = mock_conn

        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Reflection",
            metadata={"k": "v", "n": 1},
        )

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.add(event)

        assert mock_cursor.execute.call_args is not None
        params = mock_cursor.execute.call_args[0][1]
        metadata_param = params[-1]
        assert isinstance(metadata_param, Jsonb)
        assert metadata_param.obj == {"k": "v", "n": 1}

    @patch("atman.reflection.store.psycopg")
    def test_get_commits_after_select(self, mock_psycopg: Mock) -> None:
        """Read methods commit so connections do not stay ``idle in transaction``."""
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.get(1)

        assert mock_conn.commit.called

    @patch("atman.reflection.store.psycopg")
    def test_list_recent_commits_after_select(self, mock_psycopg: Mock) -> None:
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.list_recent(uuid4(), limit=5)

        assert mock_conn.commit.called

    @patch("atman.reflection.store.psycopg")
    def test_list_by_session_commits_after_select(self, mock_psycopg: Mock) -> None:
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.list_by_session(uuid4())

        assert mock_conn.commit.called

    @patch("atman.reflection.store.psycopg")
    def test_list_by_level_commits_after_select(self, mock_psycopg: Mock) -> None:
        from atman.reflection.store import ReflectionStore

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        store = ReflectionStore(db_url="postgresql://test:pass@localhost/db")
        store._conn = mock_conn
        store.list_by_level(uuid4(), ReflectionLevel.DAILY)

        assert mock_conn.commit.called
