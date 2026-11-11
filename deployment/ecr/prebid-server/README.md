# Prebid Server Container Image

This directory holds the Docker build context for the Prebid Server container image, including the two supported Dockerfiles and the `docker-build-config.json` selection contract.

## Base image selection

The image can be built from two bases. Select one with the `--base` flag on `deployment/ecr/build-image.sh`:

| Base | Flag | Dockerfile | Base images | Notes |
|---|---|---|---|---|
| Amazon Linux 2023 | `--base al2023` (**default**) | `Dockerfile.al2023` | `amazoncorretto:21-al2023` → `amazonlinux:2023-minimal` | Default. Larger image; glibc/dnf ecosystem alignment. |
| Alpine (jlink-tuned) | `--base alpine` | `Dockerfile.alpine` | `alpine:3.23.3` | Retains the `jlink` custom-JRE tuning (`--strip-debug`, `--no-man-pages`, `--no-header-files`, `--compress=2`) and the `apk upgrade zlib musl musl-utils` CVE fix. Size-optimized. |

The closed set of bases (`{al2023, alpine}`), the default (`al2023`), and the base→Dockerfile mapping are defined in `docker-build-config.json`. `build-image.sh` validates `--base` against that set before invoking the container runtime and fails non-zero on an unsupported value. Both paths honor the `INCLUDE_AMT_BIDDER` build arg.

```bash
cd deployment/ecr
./build-image.sh --base al2023   # default
./build-image.sh --base alpine
```

### Size comparison and tradeoff (linux/amd64 deploy target)

| Base | Size | Relative |
|---|---|---|
| Alpine (jlink-tuned) | ≈ 351 MiB (368,459,776 bytes) | ~36% smaller |
| AL2023 | ≈ 547 MiB (573,870,080 bytes) | ~1.56× the Alpine size |

Sizes measured with `finch image inspect --format '{{.Size}}'`; absolute difference ≈ 196 MiB. The jlink-tuned Alpine base is the size-optimized path; AL2023 is the larger, default base with the glibc/dnf alignment many teams prefer.

## AMT Bidder Directory

This directory `amt-bidder` is intentionally maintained as empty in version control.

- **For deployments without bidder simulator**: Leave empty which empty directory ensures Docker COPY commands succeed regardless of deployment type.
- **For deployments with bidder simulator**: When using `./deploy.sh --deploy-bidding-simulator` the script will populate this directory with the necessary prebid adapter source code files from source/loadtest/amt-bidder
 