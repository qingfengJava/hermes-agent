"""
分布式唯一 ID 生成器（雪花算法变体）。

使用 64 位长整型：
- 41 位：毫秒级时间戳（可用 69 年）
- 10 位：工作节点 ID（0-1023）
- 12 位：序列号（0-4095）
- 1 位：保留

在未配置工作节点 ID 时，使用随机数作为节点标识。
"""

import os
import random
import threading
import time

# 起始时间戳（2024-01-01 00:00:00 UTC），41 位能用到 2093 年
EPOCH_MS = 1704067200000

# 位数分配
WORKER_ID_BITS = 10
SEQUENCE_BITS = 12

MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1

# 位移量
TIMESTAMP_SHIFT = WORKER_ID_BITS + SEQUENCE_BITS
WORKER_ID_SHIFT = SEQUENCE_BITS


class IdGenerator:
    """
    线程安全的分布式唯一 ID 生成器。

    用法:
        generator = IdGenerator(worker_id=1)
        new_id = generator.next_id()
    """

    def __init__(self, worker_id: int = None):
        """
        初始化 ID 生成器。

        参数:
            worker_id: 工作节点编号（0-1023）。
                       为 None 时根据环境变量 HERMES_WORKER_ID 或 PID 自动确定。
        """
        if worker_id is None:
            worker_id = self._resolve_worker_id()
        if worker_id < 0 or worker_id > MAX_WORKER_ID:
            raise ValueError(f"worker_id 必须在 0 到 {MAX_WORKER_ID} 之间")
        self._worker_id = worker_id
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_timestamp = -1

    @staticmethod
    def _resolve_worker_id() -> int:
        """解析工作节点 ID：环境变量 → PID 取模 → 随机数"""
        env_id = os.getenv("HERMES_WORKER_ID")
        if env_id is not None:
            try:
                return int(env_id) & MAX_WORKER_ID
            except ValueError:
                pass
        # 使用 PID 的低 10 位加随机因子避免同一台机器上多进程冲突
        pid_part = os.getpid() & 0x3FF
        random_part = random.randint(0, MAX_WORKER_ID)
        return (pid_part ^ random_part) & MAX_WORKER_ID

    def next_id(self) -> int:
        """生成并返回下一个全局唯一 ID"""
        with self._lock:
            timestamp = self._current_millis()
            if timestamp < self._last_timestamp:
                # 时钟回拨：等待直到追上
                drift = self._last_timestamp - timestamp
                if drift < 5000:
                    time.sleep(drift / 1000.0)
                    timestamp = self._current_millis()
                else:
                    raise RuntimeError(f"时钟回拨过大 ({drift}ms)，拒绝生成 ID")

            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    # 当前毫秒序列号用完，等待下一毫秒
                    timestamp = self._wait_next_millis(self._last_timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = timestamp
            return (
                ((timestamp - EPOCH_MS) << TIMESTAMP_SHIFT)
                | (self._worker_id << WORKER_ID_SHIFT)
                | self._sequence
            )

    @staticmethod
    def _current_millis() -> int:
        """当前 Unix 毫秒时间戳"""
        return int(time.time() * 1000)

    @staticmethod
    def _wait_next_millis(last_timestamp: int) -> int:
        """自旋等待直到下一毫秒"""
        timestamp = int(time.time() * 1000)
        while timestamp <= last_timestamp:
            timestamp = int(time.time() * 1000)
        return timestamp


# 进程级单例
_generator: IdGenerator = None
_generator_lock = threading.Lock()


def get_id_generator() -> IdGenerator:
    """获取进程级 ID 生成器单例（线程安全）"""
    global _generator
    if _generator is None:
        with _generator_lock:
            if _generator is None:
                _generator = IdGenerator()
    return _generator
