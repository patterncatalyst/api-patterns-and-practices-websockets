#!/usr/bin/env bash
#
# build-images.sh — build both app images inside OpenShift Local. No host
# container engine, no exposed registry, and the cluster never pulls from
# Maven Central / PyPI over the open internet beyond what each build already
# does on the host (Maven) / inside the cluster (the Python Docker-strategy
# build, which runs the project's own Containerfile verbatim).
#
#   ./openshift/build-images.sh                 # both images
#   ./openshift/build-images.sh quarkus         # just the Quarkus image
#   ./openshift/build-images.sh python          # just the Python image
#
# Quarkus: Maven packages the fast-jar on the HOST (target/quarkus-app); the
# inactive `openshift` Maven profile (../quarkus/pom.xml, requires
# -Popenshift) then uploads it to a binary S2I BuildConfig that
# quarkus-openshift generates, which runs on ubi10/openjdk-25 inside the
# cluster and pushes ImageStream tag part4-backplane-quarkus:$IMAGE_TAG.
#
# Python: there is no Quarkus-equivalent S2I extension for Python, so this
# assembles a throwaway build context containing exactly what
# ../python/Containerfile's COPY lines need (repo-root-relative paths, since
# that Containerfile is built with the REPO ROOT as context — see
# ../../k8s/verify-minikube.sh's `docker build ... "$REPO_ROOT"`), then runs
# that Containerfile as a Docker-strategy BuildConfig IN the cluster via
# `oc new-build --strategy=docker` + `oc start-build --from-dir`.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Newest UBI with the newest JDK, exact tag. With the OpenShift S2I build
# strategy, quarkus.openshift.base-jvm-image is the S2I BUILDER image — the
# build runs its `/usr/libexec/s2i/assemble` to lay the fast-jar in — so it
# MUST be the full `ubi10/openjdk-25` image, which ships the s2i scripts AND
# run-java.sh. The `-runtime` variant has no s2i scripts (the S2I step fails
# with `assemble: No such file or directory` — confirmed live on CRC
# 2026-10-19), so it works only for a Docker/Containerfile multistage FROM,
# not here. Re-check with
# `skopeo list-tags docker://registry.access.redhat.com/ubi10/openjdk-25`;
# bump deliberately, never silently.
BASE_JVM_IMAGE="${BASE_JVM_IMAGE:-registry.access.redhat.com/ubi10/openjdk-25:1.24-16}"

require_crc
oc get project "$NS" >/dev/null 2>&1 || fail "project $NS missing: run ./openshift/install-infra.sh first"

targets=("$@")
(( ${#targets[@]} )) || targets=(quarkus python)

for t in "${targets[@]}"; do
    case "$t" in
        quarkus|python) ;;
        *) fail "unknown target '$t' (expected 'quarkus' and/or 'python')" ;;
    esac
done

build_quarkus() {
    command -v mvn >/dev/null 2>&1 || fail "mvn not on PATH"
    step "Quarkus: binary S2I build (part4-backplane-quarkus:$IMAGE_TAG, $BASE_JVM_IMAGE)"
    # quarkus.openshift.version sets the BuildConfig's output tag; with only
    # quarkus.container-image.tag it stays at the project version
    # (1.0.0-SNAPSHOT). quarkus.kubernetes.deploy=false: build and push only,
    # the Helm chart owns the Deployments. quarkus.openshift.namespace is the
    # ONE that selects the target project — Quarkus 3.40 ignores
    # quarkus.kubernetes-client.namespace/KUBERNETES_NAMESPACE for the
    # openshift build, and `crc start` resets the kubeconfig context
    # namespace to `default`.
    ( cd "$REPO_ROOT/examples/part4-backplane/quarkus" && mvn -B package -DskipTests -Popenshift \
        -Dquarkus.container-image.build=true \
        -Dquarkus.container-image.name=part4-backplane-quarkus \
        -Dquarkus.container-image.tag="$IMAGE_TAG" \
        -Dquarkus.openshift.version="$IMAGE_TAG" \
        -Dquarkus.openshift.base-jvm-image="$BASE_JVM_IMAGE" \
        -Dquarkus.openshift.namespace="$NS" \
        -Dquarkus.kubernetes.deploy=false ) \
        || fail "Quarkus S2I build failed (oc get builds -n $NS; oc logs build/part4-backplane-quarkus-1 -n $NS)"
}

build_python() {
    step "Python: Docker-strategy BuildConfig (part4-backplane-python:$IMAGE_TAG)"
    local src="$REPO_ROOT/examples/part4-backplane/python"
    local ctx
    ctx="$(mktemp -d -t part4-backplane-python-build-ctx.XXXXXX)"
    # EXIT trap (not RETURN): `fail` exits the script, which bypasses a RETURN
    # trap and would leak the mktemp dir. $ctx is expanded now (by value) so
    # the trap still has the path after this local goes out of scope.
    trap "rm -rf '$ctx'" EXIT

    # Mirror EXACTLY the repo-root-relative paths ../python/Containerfile's
    # COPY lines reference — the Containerfile is built with the repo root
    # as context (never this module's own directory), so the build context
    # directory tree has to reproduce that same layout. Each stage is guarded:
    # a missing source must fail loudly HERE, not as a confusing in-cluster
    # build error against an incomplete context.
    mkdir -p "$ctx/examples/part4-backplane/python" \
             "$ctx/examples/part3-handling-events/fixtures" \
             "$ctx/contracts" \
             "$ctx/scripts" || fail "stage: mkdir build context tree"
    cp "$src/pyproject.toml" "$ctx/examples/part4-backplane/python/" || fail "stage: pyproject.toml"
    cp "$src/uv.lock" "$ctx/examples/part4-backplane/python/" || fail "stage: uv.lock"
    cp -r "$src/app" "$ctx/examples/part4-backplane/python/app" || fail "stage: app/"
    cp "$src/Containerfile" "$ctx/examples/part4-backplane/python/" || fail "stage: Containerfile"
    cp "$REPO_ROOT/contracts/asyncapi.yaml" "$ctx/contracts/" || fail "stage: contracts/asyncapi.yaml"
    cp "$REPO_ROOT/scripts/extract-message-schema.py" "$ctx/scripts/" || fail "stage: scripts/extract-message-schema.py"
    cp "$REPO_ROOT/examples/part3-handling-events/fixtures/handling-events.json" \
       "$ctx/examples/part3-handling-events/fixtures/" || fail "stage: part3 fixtures/handling-events.json"

    if ! oc get bc part4-backplane-python -n "$NS" >/dev/null 2>&1; then
        oc new-build --name=part4-backplane-python --binary --strategy=docker \
            --to="part4-backplane-python:$IMAGE_TAG" -n "$NS" >/dev/null \
            || fail "oc new-build part4-backplane-python"
    else
        ok "BuildConfig part4-backplane-python already exists"
    fi
    # dockerfilePath is relative to the build context root (the $ctx tree
    # above), matching ../python/Containerfile's own COPY paths. The build
    # compiles aiokafka's C extension from source (gcc/make/zlib-devel,
    # discarded after the build stage — see that Containerfile's note) and
    # generates app/models_generated.py: heavier than a typical S2I jar
    # upload, so the default build-pod resources are raised.
    oc patch bc part4-backplane-python -n "$NS" --type=merge -p '{
        "spec": {
            "strategy": {
                "dockerStrategy": {
                    "dockerfilePath": "examples/part4-backplane/python/Containerfile"
                }
            },
            "output": {"to": {"kind": "ImageStreamTag", "name": "part4-backplane-python:'"$IMAGE_TAG"'"}},
            "resources": {
                "requests": {"cpu": "1", "memory": "2Gi"},
                "limits": {"cpu": "2", "memory": "4Gi"}
            }
        }
    }' >/dev/null || fail "oc patch bc part4-backplane-python"

    oc start-build part4-backplane-python -n "$NS" --from-dir="$ctx" --follow --wait \
        || fail "Python Docker-strategy build failed (oc get builds -n $NS -l buildconfig=part4-backplane-python; oc logs -f bc/part4-backplane-python -n $NS)"
}

for t in "${targets[@]}"; do
    case "$t" in
        quarkus) build_quarkus ;;
        python)  build_python ;;
    esac
done

step "Verifying ImageStream tags"
for svc in "${SERVICES[@]}"; do
    case "$svc" in
        part4-backplane-quarkus) [[ " ${targets[*]} " == *" quarkus "* ]] || continue ;;
        part4-backplane-python)  [[ " ${targets[*]} " == *" python "* ]] || continue ;;
    esac
    ref="$(oc get istag "$svc:$IMAGE_TAG" -n "$NS" -o jsonpath='{.image.dockerImageReference}' 2>/dev/null)" \
        || fail "no ImageStream tag $svc:$IMAGE_TAG"
    ok "$svc:$IMAGE_TAG ${ref##*@}"
done
