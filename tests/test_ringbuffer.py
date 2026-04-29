"""Test the ring buffer used for audio streaming."""

import numpy as np
from learntoplayit.ringbuffer import RingBuffer


def test_empty_read():
    rb = RingBuffer(capacity=100, channels=2)
    out = rb.read(10)
    assert len(out) == 0


def test_write_then_read():
    rb = RingBuffer(capacity=100, channels=2)
    data = np.ones((10, 2), dtype=np.float32)
    written = rb.write(data)
    assert written == 10
    assert rb.available() == 10
    out = rb.read(10)
    assert np.array_equal(out, data)
    assert rb.available() == 0


def test_wraparound():
    rb = RingBuffer(capacity=16, channels=1)
    data = np.arange(12, dtype=np.float32).reshape(-1, 1)
    rb.write(data)
    rb.read(12)
    data2 = np.arange(100, 110, dtype=np.float32).reshape(-1, 1)
    rb.write(data2)
    out = rb.read(10)
    assert np.array_equal(out, data2)


def test_write_overflow_clamps():
    rb = RingBuffer(capacity=8, channels=1)
    data = np.ones((20, 1), dtype=np.float32)
    written = rb.write(data)
    assert written == 8
    assert rb.available() == 8
    assert rb.free() == 0


def test_read_underflow_clamps():
    rb = RingBuffer(capacity=100, channels=1)
    data = np.ones((5, 1), dtype=np.float32)
    rb.write(data)
    out = rb.read(50)
    assert len(out) == 5


def test_flush():
    rb = RingBuffer(capacity=100, channels=2)
    rb.write(np.ones((50, 2), dtype=np.float32))
    assert rb.available() == 50
    rb.flush()
    assert rb.available() == 0


def test_peek():
    rb = RingBuffer(capacity=100, channels=1)
    data = np.arange(5, dtype=np.float32).reshape(-1, 1)
    rb.write(data)
    peeked = rb.peek(5)
    assert np.array_equal(peeked, data)
    assert rb.available() == 5
    out = rb.read(5)
    assert np.array_equal(out, data)


def test_alternating_read_write():
    rb = RingBuffer(capacity=8, channels=1)
    for i in range(20):
        d = np.array([[float(i)]], dtype=np.float32)
        rb.write(d)
        out = rb.read(1)
        assert out[0, 0] == float(i)
