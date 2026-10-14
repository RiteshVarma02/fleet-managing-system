"""OccupancyGrid <-> image conversion for the fleet map (no ROS node here).

V1 has one fleet map and every robot keeps its own copy of it, so the server
no longer republishes `/map`; maps reach robots through fleet file sync.
"""

from __future__ import annotations

from typing import Any

from app.ros.runtime import RosModules


def build_occupancy_grid(ros: RosModules, image_gray, resolution: float, origin_x: float, origin_y: float):
    """Convert a grayscale PIL image into a nav_msgs/OccupancyGrid.

    Vectorised with numpy — the naive per-pixel Python loop is O(n) round
    trips and takes seconds on a real 4000x4000 map.
    """
    import numpy as np

    arr = np.asarray(image_gray, dtype=np.uint8)
    # ROS occupancy grids are row-major starting at the bottom-left corner,
    # while image row 0 is the top row.
    arr = np.flipud(arr)
    height, width = arr.shape

    occupancy = np.full(arr.shape, -1, dtype=np.int8)
    occupancy[arr > 250] = 0
    occupancy[arr < 5] = 100

    grid = ros.OccupancyGrid()
    grid.header.frame_id = "map"
    grid.info.resolution = float(resolution)
    grid.info.width = int(width)
    grid.info.height = int(height)
    grid.info.origin.position.x = float(origin_x)
    grid.info.origin.position.y = float(origin_y)
    grid.info.origin.position.z = 0.0
    grid.info.origin.orientation.w = 1.0
    grid.data = occupancy.flatten().tolist()
    return grid


def occupancy_grid_to_image(grid) -> tuple[Any, dict]:
    """Convert a nav_msgs/OccupancyGrid back into a grayscale PIL image.

    Inverse of `build_occupancy_grid`: free (0) maps to white, occupied (100)
    to black and unknown (-1) to mid-grey. The grid's rows run bottom-up, so
    the image is flipped back to the top-down convention PIL uses.

    Returns ``(image, metadata)`` where ``image`` is an ``PIL.Image`` in "L"
    mode and ``metadata`` holds width/height/resolution/origin_x/origin_y.
    """
    import numpy as np
    from PIL import Image as PILImage

    height = int(grid.info.height)
    width = int(grid.info.width)

    data = np.asarray(grid.data, dtype=np.int8).reshape((height, width))
    # 0 -> free (white), 100 -> occupied (black), anything else -> unknown.
    image = np.full(data.shape, 205, dtype=np.uint8)
    image[data == 0] = 254
    image[data == 100] = 0

    pil_image = PILImage.fromarray(np.flipud(image), mode="L")
    metadata = {
        "width": width,
        "height": height,
        "resolution": float(grid.info.resolution),
        "origin_x": float(grid.info.origin.position.x),
        "origin_y": float(grid.info.origin.position.y),
    }
    return pil_image, metadata
