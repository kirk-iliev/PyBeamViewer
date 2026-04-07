"""Unit tests for analysis.trending_buffer.TrendingBuffer."""

import numpy as np
import pytest

from analysis.trending_buffer import FIELDS, TrendingBuffer


class TestTrendingBufferBasic:
    """Append, read, and lifecycle operations."""

    def test_empty_buffer(self):
        buf = TrendingBuffer(max_len=10)
        h = buf.get_history()
        assert buf.count == 0
        for f in FIELDS:
            assert f in h
            assert len(h[f]) == 0

    def test_single_append(self):
        buf = TrendingBuffer(max_len=5)
        buf.append({"frame_number": 1.0, "sigma_x": 42.0})
        assert buf.count == 1
        h = buf.get_history()
        assert h["frame_number"][0] == 1.0
        assert h["sigma_x"][0] == 42.0
        assert np.isnan(h["sigma_y"][0])  # missing field defaults to NaN

    def test_multiple_appends_order(self):
        buf = TrendingBuffer(max_len=10)
        for i in range(5):
            buf.append({"frame_number": float(i)})
        h = buf.get_history()
        assert len(h["frame_number"]) == 5
        np.testing.assert_array_equal(h["frame_number"], [0, 1, 2, 3, 4])

    def test_wrap_around(self):
        buf = TrendingBuffer(max_len=3)
        for i in range(5):
            buf.append({"frame_number": float(i), "sigma_x": float(i * 10)})
        assert buf.count == 3  # max_len
        h = buf.get_history()
        # Should contain the last 3 entries: 2, 3, 4
        np.testing.assert_array_equal(h["frame_number"], [2, 3, 4])
        np.testing.assert_array_equal(h["sigma_x"], [20, 30, 40])

    def test_clear(self):
        buf = TrendingBuffer(max_len=5)
        for i in range(3):
            buf.append({"frame_number": float(i)})
        buf.clear()
        assert buf.count == 0
        h = buf.get_history()
        for f in FIELDS:
            assert len(h[f]) == 0


class TestUpdateLatestRoi:
    """Back-filling ROI sigma into the latest entry."""

    def test_update_latest_roi(self):
        buf = TrendingBuffer(max_len=5)
        buf.append({"frame_number": 1.0})
        assert np.isnan(buf.get_history()["roi_sigma_x"][0])

        buf.update_latest_roi(roi_sigma_x=12.5, roi_sigma_y=8.3)
        h = buf.get_history()
        assert h["roi_sigma_x"][0] == 12.5
        assert h["roi_sigma_y"][0] == 8.3

    def test_update_latest_roi_empty_buffer(self):
        """Should not raise when buffer is empty."""
        buf = TrendingBuffer(max_len=5)
        buf.update_latest_roi(roi_sigma_x=1.0, roi_sigma_y=2.0)
        assert buf.count == 0

    def test_update_latest_after_wrap(self):
        buf = TrendingBuffer(max_len=3)
        for i in range(5):
            buf.append({"frame_number": float(i)})
        # Latest entry is frame 4
        buf.update_latest_roi(roi_sigma_x=99.0, roi_sigma_y=88.0)
        h = buf.get_history()
        assert h["roi_sigma_x"][-1] == 99.0
        assert h["roi_sigma_y"][-1] == 88.0
        # Earlier entries should still be NaN
        assert np.isnan(h["roi_sigma_x"][0])


class TestResize:
    """Capacity changes preserve recent history."""

    def test_resize_down(self):
        buf = TrendingBuffer(max_len=10)
        for i in range(8):
            buf.append({"frame_number": float(i)})
        buf.resize(3)
        h = buf.get_history()
        assert len(h["frame_number"]) == 3
        # Should keep the most recent 3
        np.testing.assert_array_equal(h["frame_number"], [5, 6, 7])

    def test_resize_up(self):
        buf = TrendingBuffer(max_len=3)
        for i in range(3):
            buf.append({"frame_number": float(i)})
        buf.resize(10)
        h = buf.get_history()
        assert len(h["frame_number"]) == 3
        np.testing.assert_array_equal(h["frame_number"], [0, 1, 2])

        # Can now add more without wrapping
        for i in range(3, 8):
            buf.append({"frame_number": float(i)})
        h = buf.get_history()
        assert len(h["frame_number"]) == 8
        np.testing.assert_array_equal(h["frame_number"], list(range(8)))

    def test_resize_after_wrap(self):
        buf = TrendingBuffer(max_len=3)
        for i in range(5):  # wraps at 3
            buf.append({"frame_number": float(i)})
        buf.resize(2)
        h = buf.get_history()
        assert len(h["frame_number"]) == 2
        np.testing.assert_array_equal(h["frame_number"], [3, 4])


class TestGetHistoryCopies:
    """Ensure returned arrays are independent copies."""

    def test_returned_arrays_are_copies(self):
        buf = TrendingBuffer(max_len=5)
        buf.append({"frame_number": 1.0, "sigma_x": 10.0})
        h1 = buf.get_history()
        h1["sigma_x"][0] = 999.0  # mutate the copy
        h2 = buf.get_history()
        assert h2["sigma_x"][0] == 10.0  # original unchanged
