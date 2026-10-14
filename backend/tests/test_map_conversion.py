"""OccupancyGrid <-> grayscale image conversion tests.

Covers the two conversion functions in `app/ros/map_codec.py`:
`build_occupancy_grid` (image -> grid) and `occupancy_grid_to_image`
(grid -> image). The inverse-mapping and the bottom-up/top-down row flip must
round-trip exactly so a map saved from a robot and re-published look identical.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.ros.map_codec import build_occupancy_grid, occupancy_grid_to_image

# Classes in a nav_msgs/OccupancyGrid: 0 free, 100 occupied, -1 unknown.
FREE = 0
OCCUPIED = 100
UNKNOWN = -1

# The grey values the image pipeline uses (see occupancy_grid_to_image).
FREE_PIXEL = 254
OCCUPIED_PIXEL = 0
UNKNOWN_PIXEL = 205


class _FakeOccupancyGrid:
    """Duck-typed rclpy message so the tests run without ROS installed."""

    def __init__(self) -> None:
        self.header = SimpleNamespace(frame_id="map")
        self.info = SimpleNamespace(
            resolution=0.0,
            width=0,
            height=0,
            origin=SimpleNamespace(
                position=SimpleNamespace(x=0.0, y=0.0, z=0.0),
                orientation=SimpleNamespace(w=1.0),
            ),
        )
        self.data: list = []


class _FakeRos:
    OccupancyGrid = _FakeOccupancyGrid


def _round_trip(image: Image.Image, resolution: float, origin_x: float, origin_y: float):
    grid = build_occupancy_grid(_FakeRos(), image, resolution, origin_x, origin_y)
    return occupancy_grid_to_image(grid)


def test_build_occupancy_grid_maps_pixel_classes():
    """White/black/mid-grey pixels become free/occupied/unknown cells."""
    image = Image.fromarray(
        np.array([[FREE_PIXEL, OCCUPIED_PIXEL, UNKNOWN_PIXEL]], dtype=np.uint8), mode="L"
    )
    grid = build_occupancy_grid(_FakeRos(), image, 0.05, -1.0, -2.0)
    assert list(grid.data) == [FREE, OCCUPIED, UNKNOWN]


def test_occupancy_grid_to_image_maps_cell_classes():
    """Free/occupied/unknown cells become white/black/mid-grey pixels."""
    grid = _FakeOccupancyGrid()
    grid.info.resolution = 0.05
    grid.info.width = 3
    grid.info.height = 1
    grid.data = [FREE, OCCUPIED, UNKNOWN]
    image, metadata = occupancy_grid_to_image(grid)
    pixels = list(np.asarray(image, dtype=np.uint8).flatten())
    assert pixels == [FREE_PIXEL, OCCUPIED_PIXEL, UNKNOWN_PIXEL]


def test_round_trip_preserves_metadata():
    """Resolution and origin survive the image -> grid -> image loop."""
    image = Image.fromarray(np.zeros((4, 5), dtype=np.uint8), mode="L")
    rebuilt, metadata = _round_trip(image, resolution=0.1, origin_x=-3.5, origin_y=2.25)
    assert metadata == {
        "width": 5,
        "height": 4,
        "resolution": 0.1,
        "origin_x": -3.5,
        "origin_y": 2.25,
    }
    assert rebuilt.size == (5, 4)


def test_round_trip_preserves_orientation():
    """The bottom-up grid row order must not mirror the image."""
    # Distinct quadrants so any accidental mirror becomes visible.
    top = np.full((4, 8), UNKNOWN_PIXEL, dtype=np.uint8)
    bottom = np.full((4, 8), UNKNOWN_PIXEL, dtype=np.uint8)
    top[:, :4] = FREE_PIXEL
    bottom[:, 4:] = OCCUPIED_PIXEL
    image = Image.fromarray(np.vstack([top, bottom]), mode="L")

    rebuilt, _ = _round_trip(image, resolution=0.05, origin_x=0.0, origin_y=0.0)
    assert np.array_equal(np.asarray(rebuilt, dtype=np.uint8), np.asarray(image, dtype=np.uint8))


def test_round_trip_is_identity_for_mixed_map():
    """A realistic mixed map (obstacles, free space, unknown) round-trips exactly."""
    arr = np.full((16, 24), UNKNOWN_PIXEL, dtype=np.uint8)
    arr[2:10, 3:7] = OCCUPIED_PIXEL   # obstacle
    arr[8:14, 12:20] = FREE_PIXEL     # free corridor
    arr[1, :] = OCCUPIED_PIXEL        # wall row
    image = Image.fromarray(arr, mode="L")

    rebuilt, _ = _round_trip(image, resolution=0.05, origin_x=0.0, origin_y=0.0)
    assert np.array_equal(np.asarray(rebuilt, dtype=np.uint8), arr)


def test_grid_flip_layout_is_row_major_bottom_up():
    """Grid row 0 is the image's bottom row (ROS convention)."""
    image = Image.fromarray(
        np.array([[FREE_PIXEL], [OCCUPIED_PIXEL]], dtype=np.uint8), mode="L"
    )
    grid = build_occupancy_grid(_FakeRos(), image, 0.05, 0.0, 0.0)
    assert grid.info.width == 1
    assert grid.info.height == 2
    # Image top = grid row 1 (the last data row); image bottom = grid row 0.
    assert list(grid.data) == [OCCUPIED, FREE]
    assert grid.header.frame_id == "map"