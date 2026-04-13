import taskiq_fastapi
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from voiceya.config import CFG

result_backend = RedisAsyncResultBackend(
    redis_url=CFG.redis_uri,
    result_ex_time=5 * 60,
)

broker = RedisStreamBroker(url=CFG.redis_uri).with_result_backend(result_backend)


taskiq_fastapi.init(broker, "voiceya:app")
