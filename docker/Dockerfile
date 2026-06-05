# -----------------------------------------------------------------------------
# random-api/docker/Dockerfile
#
# Build:  docker build -t random-api random-api/docker/
# Run:    docker run --rm -p 8080:8080 random-api
#         curl http://localhost:8080/random
#
# python:3.14-alpine — small image (~55 MB), no pip packages needed.
# Exec-form CMD so ECS SIGTERM reaches the Python process directly.
# -----------------------------------------------------------------------------

FROM python:3.14-alpine

COPY app.py /app/app.py
WORKDIR /app
EXPOSE 8080
CMD ["python", "app.py"]
