#!/bin/bash
set -euo pipefail

ARCHIVE_PATH="${MONGODB_ARCHIVE_PATH:-/docker-entrypoint-initdb.d/pegasus.archive}"
TARGET_DB="${MONGODB_DATABASE:?MONGODB_DATABASE is required}"
SOURCE_DB="${MONGODB_ARCHIVE_SOURCE_DB:-$TARGET_DB}"
ROOT_USERNAME="${MONGO_INITDB_ROOT_USERNAME:?MONGO_INITDB_ROOT_USERNAME is required}"
ROOT_PASSWORD="${MONGO_INITDB_ROOT_PASSWORD:?MONGO_INITDB_ROOT_PASSWORD is required}"

if [ ! -f "$ARCHIVE_PATH" ]; then
    echo "Mongo archive not found at $ARCHIVE_PATH; skipping restore."
    exit 0
fi

declare -a RESTORE_ARGS
RESTORE_ARGS=(
    "--archive=${ARCHIVE_PATH}"
    "--username=${ROOT_USERNAME}"
    "--password=${ROOT_PASSWORD}"
    "--authenticationDatabase=admin"
    "--nsInclude=${SOURCE_DB}.*"
    "--drop"
    "--stopOnError"
)

if [ "$(od -An -tx1 -N2 "$ARCHIVE_PATH" | tr -d '[:space:]')" = "1f8b" ]; then
    RESTORE_ARGS+=("--gzip")
fi

if [ "$SOURCE_DB" != "$TARGET_DB" ]; then
    RESTORE_ARGS+=("--nsFrom=${SOURCE_DB}.*" "--nsTo=${TARGET_DB}.*")
fi

echo "Restoring Mongo archive from ${ARCHIVE_PATH} into database ${TARGET_DB}."
mongorestore "${RESTORE_ARGS[@]}"