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
