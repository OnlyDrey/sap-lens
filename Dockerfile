# syntax=docker/dockerfile:1.7
FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
# Optional session CA is mounted only during networked builds, never copied into the image.
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run check:types && npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SAP_LENS_DEPLOYMENT_MODE=server SAP_LENS_HOST=0.0.0.0 SAP_LENS_PORT=18743 \
    SAP_LENS_DATA_DIR=/data SAP_LENS_SOURCE_DIR=/sources
WORKDIR /opt/sap-lens
COPY backend/requirements.txt /tmp/requirements.txt
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; export PIP_CERT=/tmp/build-ca.pem; fi; \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt && rm -f /tmp/build-ca.pem /tmp/requirements.txt
RUN groupadd --gid 10001 saplens && useradd --uid 10001 --gid saplens --no-create-home saplens \
    && mkdir /data /sources && chown saplens:saplens /data
COPY backend/*.py ./backend/
COPY backend/routers/ ./backend/routers/
COPY assets/ ./assets/
COPY --from=frontend /build/frontend/dist ./frontend/dist/
RUN chmod -R u=rwX,go=rX /opt/sap-lens
USER 10001:10001
EXPOSE 18743
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["python", "backend/healthcheck.py"]
STOPSIGNAL SIGTERM
CMD ["python", "backend/server.py"]
