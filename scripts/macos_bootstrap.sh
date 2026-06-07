#!/bin/bash

set -e

MIN_PYTHON_VERSION="3.11"
MACOS_VENV_DIR=".venv-macos"

version_at_least() {
    "$1" - "$MIN_PYTHON_VERSION" <<'PY'
import sys

required = tuple(int(part) for part in sys.argv[1].split("."))
current = sys.version_info[: len(required)]
raise SystemExit(0 if current >= required else 1)
PY
}

find_python() {
    local candidates=()

    if [ -n "${VIRTUAL_ENV:-}" ]; then
        candidates+=("$VIRTUAL_ENV/bin/python")
    fi

    candidates+=(
        ".venv/bin/python"
        "venv/bin/python"
        "$MACOS_VENV_DIR/bin/python"
        "/opt/homebrew/bin/python3.14"
        "/opt/homebrew/bin/python3.13"
        "/opt/homebrew/bin/python3.12"
        "/opt/homebrew/bin/python3.11"
        "/opt/homebrew/bin/python3"
        "/usr/local/bin/python3.14"
        "/usr/local/bin/python3.13"
        "/usr/local/bin/python3.12"
        "/usr/local/bin/python3.11"
        "/usr/local/bin/python3"
        "python3.14"
        "python3.13"
        "python3.12"
        "python3.11"
        "python3"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1 && version_at_least "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done

    return 1
}

print_python_error() {
    cat >&2 <<EOF
エラー: Python ${MIN_PYTHON_VERSION} 以上が見つかりません。

Homebrew を使う場合:
  brew install python@3.12

インストール後、もう一度このファイルを実行してください。
EOF
}

ensure_macos_venv() {
    local python_bin
    if ! python_bin="$(find_python)"; then
        print_python_error
        return 1
    fi

    if [[ "$python_bin" != *"/bin/python" ]]; then
        "$python_bin" -m venv "$MACOS_VENV_DIR"
        python_bin="$MACOS_VENV_DIR/bin/python"
    fi

    "$python_bin" -m pip install --upgrade pip >&2
    "$python_bin" -m pip install -r requirements.txt >&2

    printf '%s\n' "$python_bin"
}
