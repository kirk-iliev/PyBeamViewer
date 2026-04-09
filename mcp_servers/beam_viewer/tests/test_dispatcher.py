"""Tests for CallbackDispatcher."""

import threading

from mcp_servers.beam_viewer.core.dispatcher import CallbackDispatcher


class TestRegisterAndEmit:
    def test_single_callback(self):
        d = CallbackDispatcher()
        results = []
        d.register("evt", lambda: results.append(1))
        d.emit("evt")
        assert results == [1]

    def test_multiple_callbacks_same_event(self):
        d = CallbackDispatcher()
        results = []
        d.register("evt", lambda: results.append("a"))
        d.register("evt", lambda: results.append("b"))
        d.register("evt", lambda: results.append("c"))
        d.emit("evt")
        assert results == ["a", "b", "c"]


class TestUnregister:
    def test_unregister_removes_callback(self):
        d = CallbackDispatcher()
        results = []
        cb = lambda: results.append(1)
        d.register("evt", cb)
        d.unregister("evt", cb)
        d.emit("evt")
        assert results == []

    def test_unregister_unknown_raises(self):
        d = CallbackDispatcher()
        try:
            d.unregister("no_such_event", lambda: None)
        except (KeyError, ValueError):
            pass
        else:
            raise AssertionError("Expected KeyError or ValueError")


class TestEmitNoCallbacks:
    def test_emit_unknown_event_is_noop(self):
        d = CallbackDispatcher()
        d.emit("nonexistent")  # should not raise


class TestArgsKwargs:
    def test_positional_args(self):
        d = CallbackDispatcher()
        received = []
        d.register("evt", lambda x, y: received.append((x, y)))
        d.emit("evt", 1, 2)
        assert received == [(1, 2)]

    def test_kwargs(self):
        d = CallbackDispatcher()
        received = []
        d.register("evt", lambda key=None: received.append(key))
        d.emit("evt", key="val")
        assert received == ["val"]

    def test_mixed_args_and_kwargs(self):
        d = CallbackDispatcher()
        received = []
        d.register("evt", lambda a, b=0: received.append((a, b)))
        d.emit("evt", 10, b=20)
        assert received == [(10, 20)]


class TestThreadSafety:
    def test_concurrent_register_and_emit(self):
        d = CallbackDispatcher()
        counter = {"n": 0}
        lock = threading.Lock()

        def increment():
            with lock:
                counter["n"] += 1

        num_threads = 50
        barrier = threading.Barrier(num_threads)

        def worker():
            barrier.wait()
            d.register("evt", increment)
            d.emit("evt")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread emitted once; the number of callbacks registered at emit
        # time varies, but counter must be > 0 and no exceptions should occur.
        assert counter["n"] > 0
