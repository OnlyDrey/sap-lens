# syntax=docker/dockerfile:1.7
FROM node:24-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package*.json frontend/
COPY scripts/product-version.mjs scripts/
COPY backend/product-version.json backend/
RUN --mount=type=secret,id=build_ca if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; npm --prefix frontend ci --no-audit --no-fund
COPY frontend/ frontend/
ARG SAP_LENS_SOURCE_SHA
ENV SAP_LENS_SOURCE_SHA=$SAP_LENS_SOURCE_SHA
RUN npm --prefix frontend run build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY backend/Directory.Build.props backend/product-version.json backend/
COPY backend/src/ backend/src/
COPY assets/ assets/
COPY --from=frontend /src/frontend/dist/ frontend/dist/
ARG SAP_LENS_SOURCE_SHA
# Optional corporate CA is ephemeral to the build, never shipped as runtime trust.
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    dotnet publish backend/src/SapLens.Api -c Release -o /out --self-contained false -p:SourceRevisionId="$SAP_LENS_SOURCE_SHA" -p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0-noble AS runtime
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libfontconfig1 libfreetype6 \
    && rm -rf /var/lib/apt/lists/* && mkdir /data && chown app:app /data
WORKDIR /app
COPY --from=build /out/ ./
COPY backend/scripts/docker/entrypoint.sh backend/scripts/docker/healthcheck.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh
ENV SAP_LENS_V2_DATA_DIR=/data SAP_LENS_V2_PORT=18795 SAP_LENS_V2_AUTH=accounts DOTNET_EnableDiagnostics=0
USER app
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["/usr/local/bin/healthcheck.sh"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--network"]
