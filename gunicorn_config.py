import re

from kombu import Connection

from pysite.constants import (
    BOT_EVENT_QUEUE, BotEventTypes, CHANNEL_DEV_LOGS, DEBUG_MODE,
    RMQ_HOST, RMQ_PASSWORD, RMQ_PORT, RMQ_USERNAME
)
from pysite.migrations.runner import run_migrations
from pysite.queues import QUEUES
from pysite.service_discovery import wait_for_rmq

STRIP_REGEX = re.compile(r"<[^<]+?>")
WIKI_TABLE = "wiki"


def when_ready(server=None):
    _when_ready(server=server)


def _when_ready(server=None, output_func=None):
    """ server hook that only runs when the gunicorn master process loads """

    if server:
        output = server.log.info
    elif output_func:
        output = output_func
    else:
        output = print

    output("Creating tables...")

    from pysite.database import RethinkDB

    db = RethinkDB(loop_type=None)
    db.conn = db.get_connection()

    # Create any table that doesn't exist
    created = db.create_tables()
    if created:
        tables = ", ".join([f"{table}" for table in created])
        output(f"Created the following tables: {tables}")

    run_migrations(db, output=output)

    output("Waiting for RabbitMQ...")

    has_rmq = wait_for_rmq()

    if not has_rmq:
        output("Timed out while waiting for RabbitMQ")
    else:
        output("RabbitMQ found, declaring RabbitMQ queues...")

        try:
            with Connection(hostname=RMQ_HOST, userid=RMQ_USERNAME, password=RMQ_PASSWORD, port=RMQ_PORT) as c:
                with c.channel() as channel:
                    for name, queue in QUEUES.items():
                        queue.declare(channel=channel)
                        output(f"Queue declared: {name}")

                    if not DEBUG_MODE:
                        producer = c.Producer()
                        producer.publish(
                            {
                                "event": BotEventTypes.send_embed.value,
                                "data": {
                                    "target": CHANNEL_DEV_LOGS,
                                    "title": "Site Deployment",
                                    "description": "The site has been deployed!"
                                }
                            },
                            routing_key=BOT_EVENT_QUEUE
                        )
        except Exception as e:
            output(f"Failed to declare RabbitMQ Queues: {e}")
