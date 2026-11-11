### Building Prebid Server Locally

The container image supports two bases. Use the `build-image.sh` helper to select one with `--base`:

```bash
cd ./deployment/ecr
./build-image.sh --base al2023   # default; Amazon Linux 2023
./build-image.sh --base alpine   # jlink-tuned Alpine (size-optimized)
```

`build-image.sh` resolves `Dockerfile.<base>` from `prebid-server/docker-build-config.json`, validates `--base` against the closed set `{al2023, alpine}` (defaulting to `al2023` when unset), and fails non-zero on an unsupported value. See [prebid-server/README.md](prebid-server/README.md) for the base-image tradeoffs and size comparison.

### Base image selection and tradeoffs

| Base | Flag | Base images | Notes |
|---|---|---|---|
| Amazon Linux 2023 | `--base al2023` (default) | `amazoncorretto:21-al2023` → `amazonlinux:2023-minimal` | Default; larger image, glibc/dnf ecosystem alignment. |
| Alpine (jlink-tuned) | `--base alpine` | `alpine:3.23.3` | `jlink` custom-JRE tuning + `apk upgrade zlib musl musl-utils` CVE fix; size-optimized. |

Measured sizes (linux/amd64 deploy target): Alpine ≈ 351 MiB, AL2023 ≈ 547 MiB (Alpine is ~36% smaller).

### Prebid Server Version and Docker Config
You can update `prebid-server-java` git tag release in `deployment/ecr/prebid-server/docker-build-config.json`. The tag must match exactly the tag on the source GitHub repository `https://github.com/prebid/prebid-server-java/tags`. After changing the tag value, rebuild the image:

```bash
cd ./deployment/ecr
./build-image.sh --base al2023   # or --base alpine
```

You can rebuild the entire stack with the new Prebid Server version using instructions in the main `README.md`.

### Running Prebid Server Locally

The `./deployment/run-local-prebid.sh` script helps you run a local instance of Prebid Server using configuration files stored in AWS.

#### Prerequisites

Before using this script, ensure you have:

1. A deployed CloudFormation stack containing the Prebid Server configuration bucket
   - The bucket must contain the necessary configuration files
   - The bucket's logical ID must contain "ConfigFilesBucket"

2. A local Docker image of Prebid Server
   - Image must be tagged as `prebid-server` (or specify custom tag with `--tag`)
   - Build the image using the Dockerfile in `./ecr/prebid/`

3. AWS credentials with permissions to:
   - List CloudFormation stack resources (if using stack lookup)
   - List and read objects from the configuration S3 bucket

4. Required tools:
   - AWS CLI configured with credentials
   - Docker installed and running
   - Bash shell

#### Basic Usage

Run using CloudFormation stack name:
```bash
./run-local-prebid.sh --stack MyStackName
```

Run using bucket name directly:
```bash
./run-local-prebid.sh --bucket my-config-bucket
```

#### Additional Options

- Mount a local directory for logs:
```bash
./run-local-prebid.sh --stack MyStackName --volume /path/to/logs
```

- Specify custom ports:
```bash
./run-local-prebid.sh --stack MyStackName --app-port 38080 --mgmt-port 38060
```

- Use specific region and image tag:
```bash
./run-local-prebid.sh --stack MyStackName --region us-west-2 --tag custom-tag
```

#### Default Ports

- Main application: `28080` (container port 8080)
- Management interface: `28060` (container port 8060)

#### Notes

- The script will copy AWS credentials from your environment or AWS CLI configuration
- Container logs are written to stdout/stderr unless a volume is mounted
- Use `--help` to see all available options


This section provides the essential information for users to understand the prerequisites and basic usage of the script, while also showing more advanced options for customization.


### S3 Settings Configuration

#### Local Development Configuration

When running Prebid Server locally using Docker, you should comment out the entire `s3` section if you don't need stored request functionality. This is important because of how the [Spring configuration works in Prebid Server](https://github.com/prebid/prebid-server-java/blob/b225eb2636fe63b526df8af34277b3203f31f9f6/src/main/java/org/prebid/server/spring/config/SettingsConfiguration.java#L231).

```yaml
settings:
  enforce-valid-account: false
  generate-storedrequest-bidrequest-id: true
  # Comment out the entire s3 section for local development without s3 stored requests
  # s3:
  #   accounts-dir: accounts
  #   stored-imps-dir: stored_imps
  #   stored-requests-dir: stored_requests
  #   stored-responses-dir: stored_responses
```
