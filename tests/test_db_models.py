from bot.db.models import Base, Broadcast, Todo, User, WordSubscription


def test_tables_registered_on_metadata():
    table_names = set(Base.metadata.tables.keys())
    assert table_names == {"users", "todos", "word_subscriptions", "broadcasts"}


def test_user_columns():
    columns = {c.name for c in User.__table__.columns}
    assert columns == {
        "user_id",
        "first_seen",
        "last_activity_at",
        "is_blocked",
        "is_dm",
    }
    assert list(User.__table__.primary_key.columns)[0].name == "user_id"


def test_todo_columns():
    columns = {c.name for c in Todo.__table__.columns}
    assert columns == {"id", "chat_id", "text", "is_done", "created_by", "created_at"}
    assert Todo.__table__.columns["chat_id"].index is True


def test_word_subscription_columns():
    columns = {c.name for c in WordSubscription.__table__.columns}
    assert columns == {"chat_id", "subscribed_at"}
    assert list(WordSubscription.__table__.primary_key.columns)[0].name == "chat_id"


def test_broadcast_columns():
    columns = {c.name for c in Broadcast.__table__.columns}
    assert columns == {
        "id",
        "admin_id",
        "text",
        "created_at",
        "sent_count",
        "failed_count",
    }
