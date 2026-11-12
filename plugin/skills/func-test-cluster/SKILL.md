---
name: func-test-cluster
allowed-tools: Bash(*), Read(*), AskUserQuestion(*)
description: >
  Set up a local test cluster for Knative func with `func cluster create`, and
  run func's cluster tests on it: the whole `make test-full`, or one job:
  integration, e2e, expose, podman, runtimes or config-ci. Use in a knative/func
  checkout when the user wants to "run the integration tests", "run e2e
  locally", "run test-full", "set up a test cluster", or runs
  "/func-test-cluster".
---

# Func Test Cluster

Create a Kind cluster with func's own `func cluster create`, then run func's
cluster tests on it. Work from the root of a knative/func checkout:
`head -1 go.mod` reads `module knative.dev/func`.

Two files are the reference. When they and this file disagree, follow them:
- `hack/test-full.sh` runs every test job on a `func cluster create` cluster.
  Its header and `setup()` list what it expects and what it exports.
- `.github/workflows/functions.yaml` has one CI job per test target, with the
  env each one sets. CI builds its clusters with `hack/cluster.sh`, not
  `func cluster create`.

## Arguments

`$ARGUMENTS` names what to run. With none, ask.

| Argument | Runs | Create flags | Also needs |
| --- | --- | --- | --- |
| `full` | `make test-full` | `--tekton --keda` | GitLab and the git server (step 5); `podman`; every runtime's toolchain |
| `integration` | `make test-integration` | `--tekton --keda` | GitLab and the git server (step 5) |
| `e2e` | `make test-e2e` | `--tekton` | |
| `expose` | `make test-e2e-expose` | `--tekton` | |
| `podman` | `make test-e2e-podman` | `--tekton` | `podman`, with `podman system service --time=0` running |
| `runtimes` | `make test-e2e-matrix` | `--tekton` | each runtime's toolchain; `FUNC_E2E_MATRIX_RUNTIMES` picks them (default: all) |
| `config-ci` | `make test-e2e-config-ci` | `--tekton` | |
| `cluster` | no tests | `--tekton --keda` | |

For one job, also export the test settings from its CI job's `env:`
(`FUNC_E2E_*`, `FUNC_INT_*`, `FUNC_TEST_*`). Skip its `KUBECONFIG` and
`FUNC_CLUSTER_*`: they belong to `hack/cluster.sh`.

## Environment

Each Bash call starts a new shell. Write these lines to a file outside the
repo and source it at the start of every command:

```sh
export FUNC_ENABLE_CLUSTER=1   # `func cluster` is experimental and refuses to run without it
FUNC_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/func"
export KUBECONFIG="$FUNC_CFG/clusters/func.local/kubeconfig.yaml"
export FUNC_E2E_KUBECONFIG="$KUBECONFIG" FUNC_INT_KUBECONFIG="$KUBECONFIG"
export FUNC_E2E_TOOLS="$FUNC_CFG/bin" PATH="$FUNC_CFG/bin:$PATH"
export FUNC_TEST_GITLAB_PASS="${FUNC_TEST_GITLAB_PASS:-test-password-123}"
```

The tests default to `hack/bin/kubeconfig.yaml` and `hack/bin/`; these lines
point them at the cluster `func cluster create` makes, as `test-full.sh` does.

## Steps

Stop at the first step that fails and report it.

1. **Build func.** `make build` writes `./func`.
2. **Host settings (the user runs these).** Do not run sudo yourself: ask the
   user to run these in their own terminal, from the repo root, and wait until
   they say so.
   - The inotify limits, which Kind needs:
     `sudo sysctl -w fs.inotify.max_user_instances=1280 fs.inotify.max_user_watches=655360`.
     It lasts until reboot. Skip it if
     `sysctl fs.inotify.max_user_instances fs.inotify.max_user_watches`
     already shows at least those values.
   - The host must trust the cluster's registry, `registry.localtest.me`, over
     plain HTTP. It is needed once per machine. Skip it if
     `/etc/docker/daemon.json` lists `registry.localtest.me` under
     `insecure-registries` and
     `/etc/docker/certs.d/registry.localtest.me/hosts.toml` exists (Docker),
     or `registries.conf` lists it (Podman). Otherwise the user runs
     `./hack/registry.sh`. Tell them first: it sets Docker's
     `insecure-registries` to `registry.localtest.me` alone, dropping any other
     entries. `func cluster create` can do this too, but it calls sudo, which
     needs the user's terminal, and it does not write the `hosts.toml` that
     Docker 29's containerd image store needs.
3. **Cluster.** A `func` cluster made by `hack/cluster.sh` blocks the create,
   and `./func cluster list` does not show it: if `hack/bin/kind get clusters`
   lists `func` and `./func cluster list` does not, remove it with
   `./hack/delete.sh`. If `./func cluster list` shows `func`, ask whether to
   reuse it. Reuse it only if it has the parts the job needs:
   `kubectl get ns tekton-pipelines keda` (`keda` only for `--keda`).
   Otherwise delete it with `./func cluster delete --skip-registry-config`.
   Then run `./func cluster create --skip-registry-config` with the flags from
   the table. It takes several minutes. It downloads kubectl, kind and act into
   `$FUNC_CFG/bin`, and installs Kind, MetalLB, Knative Serving with Contour,
   Eventing, the in-cluster registry, and Tekton with Pipelines-as-Code and
   KEDA with its HTTP add-on when asked. On failure it deletes the cluster;
   to keep it for a look, run again with `--no-cleanup`.

   Then copy the kubeconfig where the `hack/` scripts look for it:
   `mkdir -p hack/bin && cp "$KUBECONFIG" hack/bin/kubeconfig.yaml`.
   `gitlab.sh`, `git-server.sh`, `dump-logs.sh` and `delete.sh` set
   `KUBECONFIG` to that path, whatever you export. Copy it again after each
   create.
4. **Images**, for every argument but `podman` and `cluster`.
   `./hack/images.sh` pushes the func-util image built from this checkout to
   the cluster's registry, and loads a buildah image into the Kind node. It
   calls `docker`. It leaves a `func-util` binary in the repo root that
   `.gitignore` does not cover: delete it when done, or a jj repo records it
   in the working-copy commit.
5. **GitLab and git server**, for `full` and `integration`: `./hack/gitlab.sh`,
   then `./hack/git-server.sh`. GitLab takes several minutes to start.
   `test-full.sh` stops early if the `gitlab` namespace is missing.
6. **Tests.** Run the command from the table.

## What this cluster cannot test

- **Kafka.** `func cluster create` cannot install a Kafka broker yet
  (knative/func#4061), so this skill does not run `make test-integration-kafka`.
  To run it, follow CI's `test-integration-kafka` job, which uses
  `hack/cluster.sh` with `FUNC_CLUSTER_KAFKA=true`.
- **Dapr.** `func cluster create` does not install Dapr, so
  expect `TestInt_Invoke_ServiceToService`, which calls another function
  through the Dapr sidecar, to fail.
- **The func operator** is not installed either. The e2e tests notice that and
  skip their Function CR checks.
- **`make test-full` runs neither `test-e2e-expose` nor Kafka.** Run `expose`
  on its own. Also read `test-integration()` in `hack/test-full.sh`: if it runs
  `make test-templates`, test-full runs no integration tests, so run
  `integration` on its own too.

## Notes

- `func cluster create`, `gitlab.sh` and the tests run for a long time: the
  runtimes matrix allows 120 minutes. Run them in the background and wait for
  them to exit.
- On a failure, `./hack/dump-logs.sh <file>` writes the cluster's events, and
  pod logs if `stern` is installed, to `<file>`. Pick a file outside the repo.
- `./func cluster delete --skip-registry-config` removes the cluster and keeps
  the host registry settings. Without the flag it tries to undo them, with
  sudo.
