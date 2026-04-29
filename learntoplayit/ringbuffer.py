import numpy as np


class RingBuffer:
    """Single-producer, single-consumer ring buffer for audio samples.

    Thread-safe for one writer and one reader without locks, using
    monotonically increasing read/write counters with modular indexing.
    """

    def __init__(self, capacity: int, channels: int):
        self.buf = np.zeros((capacity, channels), dtype=np.float32)
        self.capacity = capacity
        self.channels = channels
        self._write_pos = 0
        self._read_pos = 0

    def available(self) -> int:
        return self._write_pos - self._read_pos

    def free(self) -> int:
        return self.capacity - self.available()

    def write(self, data: np.ndarray) -> int:
        n = len(data)
        if n == 0:
            return 0
        space = self.free()
        if n > space:
            n = space
        if n == 0:
            return 0
        start = self._write_pos % self.capacity
        end = start + n
        if end <= self.capacity:
            self.buf[start:end] = data[:n]
        else:
            first = self.capacity - start
            self.buf[start:] = data[:first]
            self.buf[:n - first] = data[first:n]
        self._write_pos += n
        return n

    def read(self, n: int) -> np.ndarray:
        avail = self.available()
        if n > avail:
            n = avail
        if n == 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        start = self._read_pos % self.capacity
        end = start + n
        if end <= self.capacity:
            out = self.buf[start:end].copy()
        else:
            first = self.capacity - start
            out = np.empty((n, self.channels), dtype=np.float32)
            out[:first] = self.buf[start:]
            out[first:] = self.buf[:n - first]
        self._read_pos += n
        return out

    def peek(self, n: int) -> np.ndarray:
        """Read without advancing the read pointer."""
        avail = self.available()
        if n > avail:
            n = avail
        if n == 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        start = self._read_pos % self.capacity
        end = start + n
        if end <= self.capacity:
            return self.buf[start:end].copy()
        first = self.capacity - start
        out = np.empty((n, self.channels), dtype=np.float32)
        out[:first] = self.buf[start:]
        out[first:] = self.buf[:n - first]
        return out

    def flush(self):
        self._read_pos = self._write_pos
