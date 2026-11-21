#!/usr/bin/env bash

status=0

allTextFiles=()
while read -r file; do
    allTextFiles+=( "$file" )
done < <( git ls-tree -r --name-only HEAD | 'grep' -E '[.](py|md|txt|sh|yml)' )

codespell "${allTextFiles[@]}" || status=1

allPythonFiles=()
while read -r file; do
    allPythonFiles+=( "$file" )
done < <( git ls-tree -r --name-only HEAD | 'grep' '[.]py$' )

ruff check --fix -- "${allPythonFiles[@]}" || status=1
black -q "${allPythonFiles[@]}" || status=1
flake8 --config tests/.flake8 "${allPythonFiles[@]}" || status=1
pylint "${allPythonFiles[@]}" | tee pylint.log
pylint_status=${PIPESTATUS[0]}
# Bits 1 and 32 mean fatal or usage error. Normal message bits are gated by the error-code check below.
if (( pylint_status & 33 )); then
    status=1
fi
if 'egrep' ': E[0-9]{4}: ' pylint.log; then
    status=1
fi
pytype -d import-error "${allPythonFiles[@]}" || status=1
mypy "${allPythonFiles[@]}" || status=1
if ! diff <( git log --all --use-mailmap --format='%aN <%aE>' | LC_ALL=C.UTF-8 sort -fu | grep -v 'no author' ) \
        <( sed '/^#/d; /^$/d' AUTHORS ); then
    echo "AUTHORS is out of date." >&2
    status=1
fi
exit $status
