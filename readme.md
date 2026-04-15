# dev 分支相对 `37aca75` 的差异

基准：`37aca75 新增进程内 OrderedDict 历史存储`
对比：`origin/dev`（HEAD `3f45684`）

## 提交列表

| 提交 | 说明 |
| --- | --- |
| `4d56e16` | refactor: audio_analyser.statics |
| `979b10d` | chore: clean up after ai & various style improvements |
| `cc32453` | feat: improved task events stream via better progress management |
| `3f45684` | feat: check audio length before create task |

## 主要变更

### 1. 创建任务前校验音频时长（`3f45684`）
- `voiceya/routers/api.py`：在 `analyse_voice.kiq()` 之前用 `av.open()` + `get_duraton_sec()` 读取时长，超过 `CFG.max_audio_duration_sec` 直接返回 HTTP 413，避免无效任务进入队列。

### 2. 事件流与进度管理重构（`cc32453`）
- 新增 `voiceya/services/events_stream.py`：集中封装 Redis Stream 发布/订阅（`get_event_publister`、`subscribe_to_events`、`subscribe_to_events_and_generate_sse`），取代原先散落在 `services/redis.py` 和 `tasks/analyser.py` 里的实现。
- `voiceya/taskiq.py`：
  - 新增 `TaskStage` 枚举（PENDING/STARTED/FAILURE/SUCCESS）和 `ProgressMiddleware`，在 `pre_send` 里写入 PENDING 进度，使 SSE 可据此区分「排队 / 执行 / 完成」。
  - 序列化由 `MSGPackSerializer` 换成 `PickleSerializer`（可直接传 `HTTPException` 等对象）。
  - `result_ex_time` 改为读取新增的 `CFG.task_result_ttl_sec`；队列 `maxlen` 改为 `max_queue_depth + max_concurrent`。
- `voiceya/config.py`：新增 `task_max_exec_sec` / `task_events_ttl_sec` / `task_result_ttl_sec` 三个可配置 TTL。
- `voiceya/services/redis.py`：移除同步连接池与事件流相关函数，只保留 async pool 与 `get_redis()`。
- `voiceya/services/sse.py`：`SSE` 继承新的 `PayloadT` 协议并实现 `to_dict()`；删除未使用的 `SSEStore`。
- `voiceya/routers/api.py` 的 `/status/{task_id}` 先通过 `broker.result_backend.get_progress` 判断任务是否存在（404），再走新的 SSE 生成器。
- `voiceya/tasks/analyser.py`：瘦身，仅保留实际分析逻辑，不再自己维护订阅循环。

### 3. `audio_analyser.statics` 重构（`4d56e16`）
- 改用一次遍历 + `defaultdict` 聚合 `durations / confidences / acoustics`，替代多次列表推导；数值计算基于 `np.array` 切片。
- 返回字段 `analysis` 改名为 `details`。

### 4. 清理与风格（`979b10d`）
- `voiceya/services/audio_analyser/engine_a.py`：删除手工落盘临时 wav 的逻辑（`_run_seg_on_bytesio`），直接 `asyncio.to_thread(SEG, sample)`；异常日志从 `exception` 降为 `error`。
- `voiceya/services/audio_analyser/audio_tools.py`、`seg.py`、`seg_analyser.py`、`__init__.py`：风格化整理。
- `pyproject.toml` / `uv.lock`：移除一项依赖（对应 `-15` 行 lock）。
- `.vscode/settings.json`：小幅调整。
