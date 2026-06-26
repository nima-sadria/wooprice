#!/usr/bin/env bash
# WooPrice Beta — Storage and backup directory setup (B4 Installer Foundation)
#
# Source from install.sh. Call setup_storage_dirs.
# Creates BETA_STORAGE_PATH/{logs,config,plugins,uploads,diagnostics}
# and BETA_BACKUP_PATH. Tracks created dirs in INSTALLER_CREATED_DIRS for rollback.

set -euo pipefail

# Accumulates created directories for rollback (space-separated paths)
INSTALLER_CREATED_DIRS=""

_track_dir() {
    INSTALLER_CREATED_DIRS="${INSTALLER_CREATED_DIRS} $1"
}

_mkdir_tracked() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        _track_dir "$dir"
        echo "  Created: ${dir}"
    else
        echo "  Exists:  ${dir}"
    fi
}

setup_storage_dirs() {
    echo "  Setting up storage directories..."
    _mkdir_tracked "${BETA_STORAGE_PATH}/logs"
    _mkdir_tracked "${BETA_STORAGE_PATH}/config"
    _mkdir_tracked "${BETA_STORAGE_PATH}/plugins"
    _mkdir_tracked "${BETA_STORAGE_PATH}/uploads"
    _mkdir_tracked "${BETA_STORAGE_PATH}/diagnostics"
    _mkdir_tracked "${BETA_BACKUP_PATH}"

    # Set restrictive permissions on the storage tree
    chmod -R 750 "${BETA_STORAGE_PATH}" "${BETA_BACKUP_PATH}" 2>/dev/null || true
    echo "  Storage directories ready."
}

rollback_storage() {
    echo "  Rolling back storage directories..."
    # Remove in reverse order (most recently created first)
    local dirs=()
    for d in $INSTALLER_CREATED_DIRS; do
        dirs+=("$d")
    done
    local i
    for (( i=${#dirs[@]}-1; i>=0; i-- )); do
        local d="${dirs[$i]}"
        if [[ -d "$d" ]]; then
            rm -rf "$d"
            echo "  Removed: ${d}"
        fi
    done
}
