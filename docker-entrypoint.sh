#!/bin/sh
set -eu

APP_USER="app"
APP_GROUP="app"
TARGET_UID="${PUID:-1000}"
TARGET_GID="${PGID:-1000}"
STATE_DIR="${STATE_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    CURRENT_GID="$(getent group "${APP_GROUP}" | cut -d: -f3)"
    if [ "${CURRENT_GID}" != "${TARGET_GID}" ]; then
        groupmod -o -g "${TARGET_GID}" "${APP_GROUP}"
    fi

    CURRENT_UID="$(id -u "${APP_USER}")"
    if [ "${CURRENT_UID}" != "${TARGET_UID}" ]; then
        usermod -o -u "${TARGET_UID}" -g "${TARGET_GID}" "${APP_USER}"
    fi

    mkdir -p "${STATE_DIR}" "/home/app"
    chown -R "${TARGET_UID}:${TARGET_GID}" "${STATE_DIR}" "/home/app"

    exec gosu "${TARGET_UID}:${TARGET_GID}" "$@"
fi

exec "$@"
