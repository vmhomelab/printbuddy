#!/bin/sh
# Typecheck, lint and knip run in parallel (all read-only and independent),
# then the tests (with the i18n parity check), then the production build. Exits non-zero if any step fails, so a type or lint error
# can't scroll past unnoticed behind a green test run.

cd frontend || exit 1

npm run typecheck > /tmp/printbuddy-typecheck.$$ 2>&1 &
typecheck_pid=$!
npm run lint > /tmp/printbuddy-lint.$$ 2>&1 &
lint_pid=$!
npm run check:knip > /tmp/printbuddy-knip.$$ 2>&1 &
knip_pid=$!

wait $typecheck_pid
typecheck_rc=$?
wait $lint_pid
lint_rc=$?
wait $knip_pid
knip_rc=$?

cat /tmp/printbuddy-typecheck.$$ /tmp/printbuddy-lint.$$ /tmp/printbuddy-knip.$$
rm -f /tmp/printbuddy-typecheck.$$ /tmp/printbuddy-lint.$$ /tmp/printbuddy-knip.$$

npm run test:run
test_rc=$?

# The production build and its browser baseline check, into a temporary
# directory: the tracked static/ is only rebuilt on purpose.
build_dir=$(mktemp -d)
npx vite build --outDir "$build_dir" --emptyOutDir && node scripts/check-browser-baseline.mjs "$build_dir/assets"
build_rc=$?
rm -rf "$build_dir"

cd ..

if [ $typecheck_rc -ne 0 ] || [ $lint_rc -ne 0 ] || [ $knip_rc -ne 0 ] || [ $test_rc -ne 0 ] || [ $build_rc -ne 0 ]; then
    echo "FAILED: typecheck=$typecheck_rc lint=$lint_rc knip=$knip_rc tests=$test_rc build=$build_rc"
    exit 1
fi
