from celery import Celery
from shared.settings import settings

# file with task definitions.
# It is necessary because python needs to load the decorators.
to_include = [
    "identity.application.accounts.tasks",
    "events.infra.tasks",
]

if settings.is_test():
    app = Celery(
        "worker",
        broker="memory://localhost/",
        backend="cache+memory://",
        include=to_include,
    )

    # Force tasks to execute locally and immediately instead of being queued
    app.conf.task_always_eager = True

    # Propagate exceptions immediately from the executed task
    app.conf.task_eager_propagates = True
else:
    app = Celery(
        "worker",
        broker=settings.RABBITMQ_DSN,
        backend=settings.QUEUE_RESULT_BACKEND_DSN,
        # Register the tasks to avoid the error "Received unregistered task of type"
        include=to_include,
    )
