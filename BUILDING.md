# Building

Everything builds and tests with **Bazel**, using a hermetic Python 3.12 and locked PyPI dependencies. You don't need a local Python setup.

## One-time setup

Install [Bazelisk](https://github.com/bazelbuild/bazelisk). It reads `.bazelversion` and fetches the matching Bazel.

## Everyday commands

```sh
bazel build //...                 # build everything
bazel test //...                  # run all tests (results are cached)
bazel run //steerrec:demo         # print steered pages for a slider sweep on synthetic data
bazel run //steerrec:demo -- --help
```

## Dependencies

- Direct Python dependencies are listed in `requirements.in`.
- They are locked, with hashes, in `requirements_lock.txt`.

To add or upgrade a dependency:

```sh
# 1. edit requirements.in
bazel run //:requirements.update  # 2. re-lock
# 3. reference it in a BUILD file as "@pypi//<name>"
```

`bazel test //...` includes `//:requirements_test`, which fails if the lock file is out of date with `requirements.in`.
