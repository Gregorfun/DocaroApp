import os
import sys
import logging
from redis import Redis
from rq import Worker, Queue

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prepend project root to sys.path so we can import app
sys.path.insert(0, '/opt/docaro')

listen = ['high', 'default', 'low']
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = Redis.from_url(redis_url)

if __name__ == '__main__':
    logger.info(f"Starting worker with Redis URL: {redis_url}")
    try:
        # Explicitly pass connection to Queues and Worker to avoid context manager issues
        queues = [Queue(name, connection=conn) for name in listen]
        worker = Worker(queues, connection=conn)
        worker.work()
    except Exception as e:
        logger.error(f"Failed to start worker: {e}")
        # Print full traceback to logs
        import traceback
        traceback.print_exc()
        sys.exit(1)
