#!/usr/bin/env bash
# Authenticate only for the push, and never push to a different branch or host.
set -euo pipefail
: "${GITHUB_TOKEN:?Missing GitHub token}"
: "${GITHUB_REF:?Missing workflow ref}"
: "${GITHUB_SERVER_URL:?Missing GitHub server URL}"
: "${GITHUB_REPOSITORY:?Missing repository name}"
if [[ "${GITHUB_REF_TYPE:-}" != branch || "$GITHUB_REF" != refs/heads/* ]] || ! git check-ref-format "$GITHUB_REF"; then
  echo '::error::Repository publication requires a branch ref.' >&2
  exit 1
fi
expected="${GITHUB_SERVER_URL%/}/${GITHUB_REPOSITORY}"
for mode in fetch push; do
  if [[ "$mode" == push ]]; then
    actual=$(git remote get-url --push --all origin)
  else
    actual=$(git remote get-url --all origin)
  fi
  if [[ "$actual" != "$expected" && "$actual" != "$expected.git" ]]; then
    echo '::error::Origin does not match the workflow repository; refusing to push.' >&2
    exit 1
  fi
done
# Git config is passed only via the environment, not stored in .git/config or
# exposed as a command-line argument. GitHub masks the original token in logs.
auth=$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w 0)
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="http.${GITHUB_SERVER_URL%/}/.extraheader"
export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $auth"
git push origin "HEAD:$GITHUB_REF"
