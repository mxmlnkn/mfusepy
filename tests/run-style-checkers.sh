#!/usr/bin/env bash

allTextFiles=()
while read -r file; do
    allTextFiles+=( "$file" )
done < <( git ls-tree -r --name-only HEAD | 'grep' -E '[.](py|md|txt|sh|yml)' )

codespell "${allTextFiles[@]}"

allPythonFiles=()
while read -r file; do
    allPythonFiles+=( "$file" )
done < <( git ls-tree -r --name-only HEAD | 'grep' '[.]py$' )

ruff check --fix -- "${allPythonFiles[@]}"
black -q "${allPythonFiles[@]}"
flake8 --config tests/.flake8 "${allPythonFiles[@]}"
pylint "${allPythonFiles[@]}" | tee pylint.log
! 'egrep' ': E[0-9]{4}: ' pylint.log
pytype -d import-error "${allPythonFiles[@]}"
mypy "${allPythonFiles[@]}"
status=$?
python3 tests/check-authors.py || status=1
exit $status
