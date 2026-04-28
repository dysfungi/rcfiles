#!/usr/bin/env sh

# Load shell environment variables from files in ~/.secrets.
_secrets_dir="${HOME}/.secrets"
if [ -d "$_secrets_dir" ]; then
  for _secret_file in "$_secrets_dir"/*; do
    [ -f "$_secret_file" ] || continue

    _secret_name=${_secret_file##*/}
    case "$_secret_name" in
    "" | *[!A-Za-z0-9_]*)
      continue
      ;;
    esac

    if printenv "$_secret_name" >/dev/null 2>&1; then
      continue
    fi

    _secret_value=$(tr -d '\r\n' <"$_secret_file")
    [ -n "$_secret_value" ] || continue

    case "$_secret_value" in
    op://*)
      continue
      ;;
    esac

    export "$_secret_name=$_secret_value"
  done
fi

unset _secrets_dir _secret_file _secret_name _secret_value
