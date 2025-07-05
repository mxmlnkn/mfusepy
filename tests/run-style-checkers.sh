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

ruff check --config tests/.ruff.toml -- "${allPythonFiles[@]}"
black -q --diff --line-length 120 --skip-string-normalization "${allPythonFiles[@]}" > black.diff
if [ -s black.diff ]; then
  cat black.diff
  exit 123
fi
flake8 --config tests/.flake8 "${allPythonFiles[@]}"
pylint --rcfile tests/.pylintrc "${allPythonFiles[@]}" | tee pylint.log
! 'egrep' ': E[0-9]{4}: ' pylint.log
pytype -d import-error "${allPythonFiles[@]}"
mypy --config-file tests/.mypy.ini "${allPythonFiles[@]}"
