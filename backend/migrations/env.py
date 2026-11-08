from alembic import context
from sqlalchemy import create_engine

from clans.live_config import LiveSettings


def run():
    settings = LiveSettings()
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
