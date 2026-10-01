#!/usr/bin/env bash
#
# Push the checked-out commit to the same branch on the GitHub mirror. Adapted from the sibling
# repos' script of the same name.
#
# Render builds from GitHub, never from Forgejo, so a deploy starts by making the commit exist there,
# on the branch the Render service follows (develop for staging). The push is a plain fast-forward,
# NEVER forced: if GitHub's branch holds a commit Forgejo does not, git refuses, the deploy stops with
# that message, and the fix is to pull GitHub's branch into Forgejo and run again.
#
# Usage: push-to-github.sh <branch>          develop | main
# Env:   HOOK          the Render deploy hook for this target — unset ⇒ nothing will deploy, skip quietly
#        MIRROR_TOKEN  a GitHub token with Contents (and Workflows) read/write on MIRROR_REPO
#        MIRROR_REPO   owner/name on github.com (repo variable DEPLOY_MIRROR_REPO)
# Exit:  0 = pushed (or deliberately skipped); 1 = a deploy is configured but cannot be published.

set -euo pipefail

BRANCH="${1:-}"
case "$BRANCH" in
  develop|main) ;;
  *) echo "::error::refusing to push '$BRANCH' — deploys go to develop (staging) or main (prod) only"; exit 1 ;;
esac

if [ -z "${HOOK:-}" ]; then
  echo "::notice::no deploy hook for $BRANCH — nothing will deploy, so nothing is pushed."
  exit 0
fi
if [ -z "${MIRROR_TOKEN:-}" ] || [ -z "${MIRROR_REPO:-}" ]; then
  echo "::error::a deploy hook is set but DEPLOY_MIRROR_TOKEN / DEPLOY_MIRROR_REPO are not — Render would rebuild a stale $BRANCH. Add them in Settings → Actions."
  exit 1
fi

# owner/name, as on github.com: a trailing .git (copied from a clone URL) would double it in the URL.
MIRROR_REPO="${MIRROR_REPO%.git}"

SHA="$(git rev-parse HEAD)"
# The token travels in a header, never in the URL: git prints remote URLs in its errors.
AUTH="$(printf 'x-access-token:%s' "$MIRROR_TOKEN" | base64 -w0)"
echo "::add-mask::$AUTH"
if ! git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $AUTH" \
     push "https://github.com/$MIRROR_REPO.git" "$SHA:refs/heads/$BRANCH"; then
  # GitHub prints why it refused (above), and there is more than one reason, so ask the remote which
  # case this is. If even reading fails, the repo name or the token is wrong, not the branch.
  if ! git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $AUTH" \
       fetch --quiet "https://github.com/$MIRROR_REPO.git" "refs/heads/$BRANCH" 2>/dev/null; then
    echo "::error::GitHub refused the push, and this job cannot even read $MIRROR_REPO@$BRANCH — check DEPLOY_MIRROR_REPO (owner/name) and that DEPLOY_MIRROR_TOKEN is valid and includes this repository."
  elif ! git merge-base --is-ancestor FETCH_HEAD "$SHA"; then
    echo "::error::GitHub's $BRANCH is not an ancestor of this commit — it has something Forgejo does not. Pull it into Forgejo's $BRANCH (git fetch github && git merge github/$BRANCH), push, and run the deploy again."
  else
    echo "::error::GitHub refused the push to $BRANCH although it is a fast-forward — read git's message above. A token permission is the usual cause (a commit touching .github/workflows/ needs Workflows: Read and write, not just Contents)."
  fi
  exit 1
fi
echo "Pushed $SHA to $MIRROR_REPO@$BRANCH."
