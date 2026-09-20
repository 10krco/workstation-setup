#!/bin/sh
set -eu

script=$(mktemp)
curl -fsSL \
  https://raw.githubusercontent.com/10krco/workstation-setup/main/provision.sh \
  -o "$script"

exec bash "$script" "$@" </dev/tty
