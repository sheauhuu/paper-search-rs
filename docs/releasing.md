# Release operations

This project publishes one Rust binary through native archives, six npm packages, and five PyPI
wheels. A `v*` tag builds all artifacts, but publication is held behind the protected GitHub
`release` environment. Do not create a release tag until the registry and environment setup below
is complete.

## Release contract

- Cargo is the version source. The Git tag must be `v<Cargo version>`.
- npm contains one main package plus five target packages at the exact same version.
- Maturin derives the wheel version from Cargo and uses `bindings = "bin"`.
- Linux wheels use the `manylinux_2_28` policy for x86_64 and arm64.
- The matrix extracts the executable from each wheel, then uses that exact file for the native
  archive and matching npm target package.
- `SHA256SUMS` covers the complete approved artifact set and is rechecked before publication.

## GitHub setup

1. Create an environment named `release` and configure required reviewers.
2. Limit deployment branches/tags to release tags as appropriate for the repository policy.
3. Keep workflow permissions restricted. The publish job alone receives `contents: write` and
   `id-token: write`.
4. Configure PyPI trusted publishing for project `paper-search-rs`, owner `sheauhuu`, repository
   `paper-search-rs`, workflow `ci.yml`, and environment `release`. PyPI pending publishers can be
   configured before the first project upload.

## First npm bootstrap

npm trusted publishing is configured per package and may require each package to exist first. For
the initial `0.2.0` release only:

1. Recheck availability of the main package and all five target package names.
2. Let the tag workflow build and verify the complete artifact set, then download that immutable
   workflow artifact.
3. Authenticate to npm interactively outside CI. Publish all five target tarballs first and publish
   `paper-search-rs-0.2.0.tgz` last.
4. Configure the GitHub Actions trusted publisher for all six npm packages, using repository
   `sheauhuu/paper-search-rs`, workflow `ci.yml`, and environment `release`.
5. Future versions use the protected publish job and do not store an npm token in GitHub.

Do not use `npm pack` output from an unverified working tree for bootstrap. Use only the artifact set
whose checksum and version validation passed in the tag workflow.

## Release order

After environment approval, automation revalidates the downloaded artifacts, then publishes in this
order:

1. Five npm target packages.
2. Five PyPI wheels through OIDC trusted publishing.
3. The main `paper-search-rs` npm package.
4. The GitHub release and its verified assets.

Publishing the main npm package last prevents users from selecting a version before its platform
packages exist.

## Failure and rollback

Registry versions are immutable. If publication fails before the main npm package is uploaded, fix
the publisher configuration and retry only the missing artifacts. If a published artifact is
invalid, deprecate the npm version or yank the PyPI release as appropriate, then issue a corrected
patch version. Never overwrite an existing version or move an existing release tag.
