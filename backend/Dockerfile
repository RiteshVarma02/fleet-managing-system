# ROS 2 base gives rclpy + std/geometry/nav/sensor messages (no Nav2 in V1).
FROM ros:humble-ros-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/app/data /srv/app/maps \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

# `exec` keeps uvicorn as PID 1 so SIGTERM reaches it and lifespan shutdown runs.
ENTRYPOINT ["/bin/bash", "-lc", "source /opt/ros/humble/setup.bash && exec \"$@\"", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
