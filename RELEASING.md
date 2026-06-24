# Releasing Printbuddy

Printbuddy's update checker uses `backend/app/core/config.py::APP_VERSION` as the running version and compares it with the newest GitHub release tag. If a release tag is created without bumping `APP_VERSION`, users can pull the newest Docker image and still see **Update available**.

## Standard release prep

1. In GitHub Actions, run **Bump APP_VERSION**.
2. Enter the release version without the leading `v`, for example `0.2.4.8`.
3. Keep `target_branch` as `dev` unless you are intentionally hotfixing `main`.
4. Wait for the workflow to push `chore: bump app version to <version>`.
5. Test the `dev` image.
6. Merge `dev` into `main`.
7. Create the matching GitHub release/tag, for example `v0.2.4.8`.

## Safety guard

The Docker publish workflow validates release builds before pushing images:

- tag build `vX.Y.Z` must have `APP_VERSION = "X.Y.Z"`
- `main` builds also validate when the pushed commit already has a `v*` tag

If the version was forgotten, Docker publish fails instead of publishing an image that permanently reports a stale app version.

## Local check

```bash
python scripts/app_version.py --print
python scripts/app_version.py --expected 0.2.4.8
python scripts/app_version.py --set 0.2.4.8
```
