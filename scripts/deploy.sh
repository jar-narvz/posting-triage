#!/usr/bin/env bash
# Deploy the current commit to the Lambda function: scripts/deploy.sh
# Runs from a Mac signed in with `aws login --profile triage --region us-east-2`, so the
# credentials are temporary and no AWS key is stored anywhere (decision 11). GitHub can't
# deploy through OIDC: the account's policy denies creating identity providers.
# Stops at the first failure, so a version that fails a check never reaches Lambda.
set -euo pipefail

AWS=(--profile triage --region us-east-2)
FUNCTION=posting-triage
REPO=posting-triage
export PATH="$HOME/.docker/bin:$PATH"  # Docker's CLI and its credential helper

fail() { echo "FAIL: $*"; exit 1; }

quietly() {  # quietly DESCRIPTION COMMAND...: run it, and show its output only if it fails
    local what="$1" out; shift
    out=$("$@" 2>&1) || { echo "$out" | tail -25; fail "$what"; }
}

# The tag names the commit, so the tree must be exactly that commit.
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || fail "not on main"
[ -z "$(git status --porcelain --untracked-files=no)" ] || fail "uncommitted changes"
TAG=$(git rev-parse --short HEAD)
echo "ok   deploying main at $TAG"

ACCT=$(aws sts get-caller-identity "${AWS[@]}" --query Account --output text) \
    || fail "not signed in: aws login --profile triage --region us-east-2"
REG="${ACCT}.dkr.ecr.us-east-2.amazonaws.com"

digest_in_ecr() {
    aws ecr describe-images --repository-name "$REPO" --image-ids imageTag="$TAG" "${AWS[@]}" \
        --query 'imageDetails[0].imageDigest' --output text 2>/dev/null || true
}

DIGEST=$(digest_in_ecr)
if [ -n "$DIGEST" ] && [ "$DIGEST" != None ]; then
    # Tags are immutable, and a rebuild would give different bytes: reuse the tested image.
    echo "ok   $TAG is already in ECR (tested when it was pushed), not rebuilding"
else
    quietly "unit tests" .venv/bin/pytest -q
    echo "ok   unit tests pass"
    quietly "docker build" docker build --platform linux/arm64 --provenance=false -t "$REPO:$TAG" .
    echo "ok   arm64 image built"
    quietly "smoke test" scripts/docker_smoke.sh "$REPO:$TAG"
    echo "ok   smoke test passes"
    aws ecr get-login-password "${AWS[@]}" | docker login --username AWS --password-stdin "$REG" >/dev/null
    docker tag "$REPO:$TAG" "$REG/$REPO:$TAG"
    quietly "docker push" docker push "$REG/$REPO:$TAG"
    DIGEST=$(digest_in_ecr)
    # A single-architecture image's local ID is its manifest digest: ECR must hold these bytes.
    [ "$DIGEST" = "$(docker image inspect -f '{{.Id}}' "$REPO:$TAG")" ] || fail "ECR digest differs from the local image"
    echo "ok   pushed to ECR"
fi

# Pinned by digest, so the function runs exactly the bytes that were tested and scanned.
PREVIOUS=$(aws lambda get-function --function-name "$FUNCTION" "${AWS[@]}" --query Code.ResolvedImageUri --output text)
aws lambda update-function-code --function-name "$FUNCTION" --image-uri "$REG/$REPO@$DIGEST" "${AWS[@]}" >/dev/null
aws lambda wait function-updated-v2 --function-name "$FUNCTION" "${AWS[@]}"
NOW=$(aws lambda get-function --function-name "$FUNCTION" "${AWS[@]}" --query Code.ResolvedImageUri --output text)
[ "$NOW" = "$REG/$REPO@$DIGEST" ] || fail "function runs ${NOW##*@}, expected $DIGEST"
echo "ok   function updated to ${DIGEST:0:19}…"

# The first request after an update is a cold start (about 16 s), so allow time.
URL=$(aws lambda get-function-url-config --function-name "$FUNCTION" "${AWS[@]}" --query FunctionUrl --output text)
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 "${URL%/}/health" || true)
[ "$code" = 200 ] || fail "/health answered $code; roll back with:
  aws lambda update-function-code --function-name $FUNCTION --image-uri ${PREVIOUS/$ACCT/\${ACCT\}} --profile triage --region us-east-2"
echo "ok   /health answers 200"

echo "deployed $TAG (previous image: ${PREVIOUS##*@})"
