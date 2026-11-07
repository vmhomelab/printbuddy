#!/bin/sh
# Typecheck and lint run in parallel (both are read-only and independent),
# then the tests. Exits non-zero if any step fails, so a type or lint error
# can't scroll past unnoticed behind a green test run.

cd frontend || exit 1

npm run typecheck > /tmp/printbuddy-typecheck.$$ 2>&1 &
typecheck_pid=$!
npm run lint > /tmp/printbuddy-lint.$$ 2>&1 &
lint_pid=$!

wait $typecheck_pid
typecheck_rc=$?
wait $lint_pid
lint_rc=$?

cat /tmp/printbuddy-typecheck.$$ /tmp/printbuddy-lint.$$
rm -f /tmp/printbuddy-typecheck.$$ /tmp/printbuddy-lint.$$

npm run test:run
test_rc=$?

cd ..

if [ $typecheck_rc -ne 0 ] || [ $lint_rc -ne 0 ] || [ $test_rc -ne 0 ]; then
    echo "FAILED: typecheck=$typecheck_rc lint=$lint_rc tests=$test_rc"
    exit 1
fi
