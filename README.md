# Guidance for Deploying a Prebid Server on AWS

## Table of Contents
1. [Overview](#overview)
2. [Cost](#cost)
3. [Prerequisites](#prerequisites)
4. [Deployment Steps](#deployment-steps)
5. [Deployment Validation](#deployment-validation)
6. [Running the Guidance](#running-the-guidance)
7. [Next Steps](#next-steps)
8. [Cleanup](#cleanup)
9. [FAQ, Known Issues, Additional Considerations, and Limitations](#faq-known-issues-additional-considerations-and-limitations)
10. [Revisions](#revisions)
11. [Notices](#notices)
12. [Authors](#authors)

## Overview

Guidance for Deploying a Prebid Server on AWS helps customers deploy and operate Prebid Server, an open source solution for real-time ad monetization, in their own AWS environment. The solution enables customers with ad-supported websites to achieve scaled access to advertising revenue through a community of more than 180+ advertising platforms. Customers achieve full control over decision logic and access to transaction data, and realize AWS benefits like global scalability and pay-as-you-go economics.

This solution deploys v3.28.0 of [Prebid Server Java](https://github.com/prebid/prebid-server-java.git) with infrastructure in a single region of the AWS Cloud to handle a wide range of request traffic, and recording of auction and bid transaction data.

### Key Features

- **Prebid Server purpose built for AWS infrastructure**: Deploy Prebid Server in a scalable and cost-efficient manner with production-grade availability, scalability, and low-latency for a variety of request loads (documented up to 100,000 RPS).

- **Built-in observability**: Operational resource metrics, alarms, runtime logs, and business metrics, visualized with the Cost and Usage Dashboard powered by Amazon QuickSight and Service Catalog AppRegistry.

- **Decrease time to market**: Deployment template to establish the necessary infrastructure to get customers running within days instead of months or weeks.

- **Ownership of all operational and business data**: All data from Prebid Server metrics extract, transform, and load (ETL) to AWS Glue Data Catalog for seamless integration with various clients, such as Amazon Athena, Amazon Redshift, and Amazon SageMaker AI.

- **AWS RTB Fabric integration**: Optionally route bid requests through [AWS RTB Fabric](https://aws.amazon.com/rtb-fabric/), a private network purpose-built for real-time bidding. RTB Fabric provides low-latency, cost-optimized connectivity between Prebid Server and bidder endpoints without traversing the public internet.

- **Quick start with bidder simulator**: Deploy an optional bidder simulator stack to quickly test and validate your Prebid Server deployment without needing to configure external bidders.

- **Demo page**: Demo page can be used to validate the end-to-end flow from prebid.js through Prebid Server to the bidder simulator (see [README](source/loadtest/demo/README.md)).

**Note**: This solution consists of two CDK stacks:
1. **Main Prebid Server Stack**: The core infrastructure for running Prebid Server (always deployed)
2. **Bidder Simulator Stack**: An optional stack for quick start testing and validation that can be deployed using the `--deploy-bidding-simulator` flag

### Architecture

The solution uses AWS CDK and AWS Solutions Constructs to create well-architected applications. All AWS Solutions Constructs are reviewed by AWS and use best practices established by the AWS Well-Architected Framework. Review the [solutions guidance landing page](https://aws.amazon.com/solutions/guidance/deploying-a-prebid-server-on-aws/) for detailed architecture diagrams.

### Overall Solution Architecture
![Guidance for Deploying a Prebid Server on AWS](docs/prebid-server-deployment-on-aws.png)

### Log Analytics Component Architecture
![Guidance for Deploying a Prebid Server on AWS - Log analytics](docs/prebid-server-deployment-on-aws-log-analytics.png)



## Cost

You are responsible for the cost of the AWS services used while running this Guidance. As of July 2023, the cost for running this Guidance with the default settings in the US East (N. Virginia) Region is approximately $241.50 per month for processing with no incoming bidding traffic to the solution.

We recommend creating a [Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) through [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) to help manage costs. Prices are subject to change. For full details, refer to the pricing webpage for each AWS service used in this Guidance.

### Sample Cost Table

The following table provides a sample cost breakdown for deploying this Guidance with the default parameters in the US East (N. Virginia) Region for one month with no incoming bidding traffic:

| AWS service  | Dimensions | Cost [USD] |
| ----------- | ------------ | ------------ |
| Amazon ECS | Operating system (Linux), CPU architecture (x86), Average duration (30 days), Number of tasks or pods (2 per month), Amount of memory allocated (4 GB), Amount of ephemeral storage allocated for Amazon ECS (20 GB) | $54.50 |
| AWS WAF | Number of Web Access Control Lists (Web ACLs) utilized (1 per month), Number of Managed Rule Groups per Web ACL (6 per month) | $15.00 |
| Elastic Load Balancing | Number of Application Load Balancers (1) | $17.00 |
| Amazon EC2 - other | Number of NAT gateways (2) DT inbound: Not selected (0 TB per month), DT outbound: Internet (<50 GB per month), DT Intra-Region: (0 TB per month) | $69.00 |
| Amazon EFS | Desired storage capacity (1 TB per month), Infrequent access requests (<2 GB per month) | $25.00 |
| Amazon S3 | S3 Standard storage | $4.00 |
| Amazon CloudWatch | Number of Standard Resolution Alarm Metrics (20), Standard logs: Data ingested (<20 GB) | $10.00 |
| Other services | Amazon CloudFront, AWS CloudTrail AWS DataSync, IAM, AWS Glue, AWS KMS, AWS Lambda, and Amazon VPC | $47.00 |
| **Total** | | **$241.50** |

**Optional: AWS RTB Fabric cost (when deployed with `--include-rtb-fabric`)**

| AWS service  | Dimensions | Cost [USD] |
| ----------- | ------------ | ------------ |
| AWS RTB Fabric | Requester Gateway, Responder Gateway, Fabric Link — no per-transaction charges with zero traffic. | $0.00 |
| AWS RTB Fabric (with 50GB traffic) | Assuming ~10 KB avg bid request, 3 AWS RTB Fabric linked internal bidders per auction, 50 GB outbound traffic (responses are DT-IN and free), internal transaction pricing ($3/billion), data transfer pricing ($0.02/GB) | $16.00 |

For current RTB Fabric pricing details, see the [AWS RTB Fabric pricing page](https://aws.amazon.com/rtb-fabric/pricing/). With incoming traffic, costs scale based on the volume and size of RTB requests sent through the Fabric Link. Note that bid responses returning to Prebid Server are data transfer IN and incur no charges.

**Cost comparison: RTB Fabric vs NAT Gateway (50GB monthly outbound traffic)**

Assuming 3 bidders per auction with ~10 KB average bid request size per bidder:
- Total data per auction: 10 KB × 3 internal bidders = 30 KB outbound
- Number of auctions: 50 GB / 30 KB ≈ 1.67 million auctions
- Total bid requests: 1.67M auctions × 3 bidders = 5 million requests (0.005 billion)
- RTB Fabric transaction cost: 0.005 billion × $3.00 = $15.00
- RTB Fabric data transfer cost: 50 GB × $0.02 = $1.00
- **Total RTB Fabric cost: $16.00**
- **NAT Gateway cost (baseline): $69.00**
- **Monthly savings: $53.00 (77% reduction)**

## Prerequisites

### Operating System

These deployment instructions are optimized to best work on **macOS, Linux, or Windows**. The following packages and tools are required:

* [AWS Command Line Interface](https://aws.amazon.com/cli/)
* [Python](https://www.python.org/) 3.11 or newer
* [Pypi/Pip](https://pypi.org/project/pip/) 25.0 or newer
* [Poetry](https://python-poetry.org/docs/#installing-with-pipx) 2.0 or newer
* [Node.js](https://nodejs.org/en/) 16.x or newer 
* [AWS CDK](https://aws.amazon.com/cdk/) 2.236.0 or newer 
* [Amazon Corretto OpenJDK](https://docs.aws.amazon.com/corretto/) 21
* [Apache Maven](https://maven.apache.org/) 3.9.9
* [Docker](https://docs.docker.com/engine/). Please ensure docker daemon is running before running cdk deployment.
  * **Alternative**: You can use [Finch](https://github.com/runfinch/finch) as a Docker Desktop alternative. Set `export CDK_DOCKER=finch` in your environment to use Finch with CDK.
* [AWS access key ID and secret access key](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html) configured in your environment with AdministratorAccess equivalent permissions

### AWS account requirements

You need an AWS account with AdministratorAccess equivalent permissions to deploy this solution.

### aws cdk bootstrap

This Guidance uses aws-cdk. If you are using aws-cdk for the first time, please perform the bootstrapping:

```bash
cdk bootstrap --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess
```

### RTB Fabric requirements

- AWS RTB Fabric must be available in your deployment region

## Deployment Steps

### 1. Quick Deploy with deploy.sh

For a streamlined deployment experience on Linux/macOS, use the provided `deploy.sh` script:

1. Clone the repo:
   ```bash
   git clone https://github.com/aws-solutions-library-samples/prebid-server-deployment-on-aws.git
   ```

2. Change to the repo folder:
   ```bash
   cd deploying-prebid-server-on-aws
   ```

3. Run the deployment script:
   ```bash
   # Deploy with analytics (most common use case)
   ./deploy.sh --enable-log-analytics --profile <your-aws-cli-profile> --region <your-region>

   # Deploy with bidder simulator
   ./deploy.sh --deploy-bidding-simulator --profile <your-aws-cli-profile> --region <your-region>

   # Deploy with bidder simulator and RTB Fabric
   ./deploy.sh --deploy-bidding-simulator --include-rtb-fabric --profile <your-aws-cli-profile> --region <your-region>

   # Deploy with all features enabled
   ./deploy.sh --deploy-bidding-simulator --include-rtb-fabric --enable-log-analytics --profile <your-aws-cli-profile> --region <your-region>
   ```

   The `deploy.sh` script automatically:
   - Copies AMT bidder files to the Docker build context when `--deploy-bidding-simulator` is used
   - Sets up the Python virtual environment
   - Installs dependencies
   - Runs CDK with the appropriate context flags

   When RTB Fabric is enabled (`--include-rtb-fabric`), the solution creates:
   - A **Requester Gateway** in the Prebid Server VPC (sends bid requests)
   - A **Responder Gateway** in the Bidder Simulator VPC (receives bid requests)
   - A **Fabric Link** connecting the two gateways through AWS RTB Fabric's private network
   - A Lambda function to automatically accept the Fabric Link

   Prebid Server is then configured to route bid requests through the RTB Fabric link URL instead of directly to the bidder simulator ALB.

   For other deployment options and usage details, run:
   ```bash
   ./deploy.sh --help
   ```

### 2. Customization, Build and Deploy

For customization or manual deployment, follow these steps:

1. Clone the repo:
   ```bash
   git clone https://github.com/aws-solutions-library-samples/prebid-server-deployment-on-aws.git
   ```

2. Change to the repo folder:
   ```bash
   cd deploying-prebid-server-on-aws
   ```

3. Create a Python virtual environment for development:
   ```bash
   python3 -m venv .venv 
   source ./.venv/bin/activate 
   cd ./source 
   pip install -r requirements-poetry.txt
   poetry install
   ```

4. After introducing changes, run the unit tests to make sure the customizations don't break existing functionality:
   ```bash
   cd ../deployment
   sh ./run-unit-tests.sh --in-venv 1
   ```

5. Build and deploy the solution:

   **Prebid Server Container Image**
   
   By default, the Prebid Server container image will be built locally using Docker ([README](deployment/ecr/README.md)). If you prefer to use a remote image (from ECR or Docker Hub), set the following environment variable with your fully qualified image name before building the template:

   ```bash
   export OVERRIDE_ECR_REGISTRY=your-fully-qualified-image-name
   ```

   **Manual Deployment with AWS CDK**
   
   If deploying with the bidder simulator, first copy the AMT bidder files:

   ```bash
   # Copy AMT bidder files (only needed when deploying with simulator)
   cp -r source/loadtest/amt-bidder deployment/ecr/prebid-server/
   ```

   Then deploy using CDK:

   ```bash
   cd source/infrastructure

   # bootstrap CDK (required once - deploys a CDK bootstrap CloudFormation stack for assets)  
   cdk bootstrap --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

   # build and deploy with bidder simulator
   cdk deploy --all --context deployBiddingSimulator=true --profile <your-aws-cli-profile> --region <your-region>

   # build and deploy with bidder simulator and RTB Fabric
   cdk deploy --all --context deployBiddingSimulator=true --context includeRtbFabric=true --profile <your-aws-cli-profile> --region <your-region>

   # or deploy without bidder simulator (no file copy needed)
   cdk deploy --all --profile <your-aws-cli-profile> --region <your-region>
   ```

   **Advanced Configuration**
   
   For advanced customization or troubleshooting, refer to the [loadtest component readme](./source/loadtest/README.md) which contains detailed information about bidder simulator configuration and manual CDK deployment instructions.

## Deployment Validation

After deploying the solution:

1. Open the CloudFormation console and verify the status of the template with the name starting with your solution name.
2. If deployment is successful, you should see an active ECS cluster with the Prebid Server tasks running.
3. Verify that the Application Load Balancer is in service.
4. If bidder simulator is deployed, follow the instructions [here](./source/loadtest/README.md) to load test the deployment.
5. Test prebid.js integration following the instructions demo website readme [here](source/loadtest/demo/README.md).

## Running the Guidance

### Prebid Server Java Container Customization

You may choose to customize the container configuration, or create your own container to use with this solution. The infrastructure for this solution has only been tested on Prebid Server Java.

#### Deploy with Customized Prebid Server Configurations
* After deploying the CloudFormation template stack, find the S3 bucket in the CloudFormation stack outputs named `ContainerImagePrebidSolutionConfigBucket`.
1. Review the `/prebid-server/default/README.md` and `/prebid-server/current/README.md` files in the bucket.
2. Upload your changes to the `/prebid-server/current/` prefix in that bucket.
3. To update the ECS service manually, navigate to the Amazon ECS cluster associated with the deployed CloudFormation stack using the AWS Management Console. Then, update the ECS service by selecting the 'Force New Deployment' option with the new task definition version.

### Runtime and Metric Logging for ETL

The Prebid Server container shipped with this solution is configured for two types of logging:

1. Runtime logs from the Prebid Server are sent to CloudWatch logs under the `PrebidContainerLogGroup` log group.
2. Metrics output logs are written to `/mnt/efs/metrics/CONTAINER_ID/prebid-metrics.log` with a default interval of 30 seconds.
3. Rotated logs are stored at `/mnt/efs/metrics/CONTAINER_ID/archived/prebid-metrics.TIMESTAMP.log.gz` and are migrated from EFS to S3 by AWS DataSync.

### Analytics Reporter Configuration

The solution includes a custom analytics adapter for Prebid Server. By default, the analytics integration is disabled in the [prebid-config.yaml](deployment/ecr/prebid-server/default-config/prebid-config.yaml)

```yaml
analytics:
  global:
    adapters: "psdoaAnalytics"  # Specifies the custom analytics adapter
  psdoa:
    enabled: ${LOG_ANALYTICS_ENABLED}  # Enables or Disables psdoa analytics integration
```

To enable psdoaAnalytics, set LOG_ANALYTICS_ENABLED=true

```bash
export LOG_ANALYTICS_ENABLED=true
```

### RTB Fabric Integration

[AWS RTB Fabric](https://aws.amazon.com/rtb-fabric/) is a private network purpose-built for real-time bidding that provides low-latency, cost-optimized connectivity between ad tech participants without traversing the public internet.

#### How It Works

When RTB Fabric is enabled (`--include-rtb-fabric`), the solution creates the following architecture:

```
Prebid Server VPC                          Bidder Simulator VPC
┌──────────────────────┐                    ┌─────────────────────┐
│  ECS Fargate Tasks   │                    │  ALB + Lambda       │
│  (Prebid Server)     │                    │  (Bidder Simulator) │
│         │            │                    │         ▲           │
│         ▼            │                    │         │           │
│  Requester Gateway ──┼── Fabric Link ─────┼── Responder Gateway │
│  (HTTPS, port 443)   │  (RTB Fabric)      │  (HTTP, port 80)    │
└──────────────────────┘                    └─────────────────────┘
```

- **Requester Gateway**: Deployed in the Prebid Server VPC. Sends bid requests over HTTPS (port 443) through RTB Fabric.
- **Responder Gateway**: Deployed in the Bidder Simulator VPC. Receives bid requests over HTTP (port 80) and forwards them to the bidder simulator ALB.
- **Fabric Link**: Connects the two gateways. Uses asymmetric security — HTTPS from requester to responder, HTTP for responses on the internal AWS network.

#### Connectivity Modes

The solution supports two connectivity modes between Prebid Server and the Bidder Simulator:

| Mode | Flag | Description |
|------|------|-------------|
| RTB Fabric | `--include-rtb-fabric` | Traffic routed through AWS RTB Fabric private network. Requires `--deploy-bidding-simulator`. |
| VPC Peering | (default when simulator is deployed) | Direct VPC peering connection between the two VPCs. Automatically configured with routes and security group rules. |

When neither mode is applicable (no bidder simulator deployed), Prebid Server connects to external bidders over the public internet through the NAT gateways.

## Next Steps

After deploying the solution, consider the following next steps:
1. **Customize Prebid Server Configuration**: Modify the configuration files in the S3 bucket to match your specific requirements.
2. **Analyze Auction Data**: Analyze the auction data generated by psdoaAnalytics adapter using AWS analytics services like Amazon Athena or Amazon Sagemaker.
3. **Set Up Monitoring**: Configure additional CloudWatch alarms or dashboards to monitor the performance of your Prebid Server.
4. **Integrate with Your Applications**: Update your client applications to use the deployed Prebid Server.
5. **Optimize for Cost**: Review the cost tables and adjust the infrastructure based on your actual traffic patterns.

## Cleanup

To delete the deployed solution, use the provided `destroy.sh` script:

```bash
# Destroy with confirmation prompts
./destroy.sh --profile <your-aws-cli-profile> --region <your-region>

# Preview what would be destroyed (no actual deletion)
./destroy.sh --dry-run --profile <your-aws-cli-profile> --region <your-region>
```

The script automatically detects which stacks are deployed (Prebid Server, Bidder Simulator) and destroys them in the correct order. RTB Fabric resources (gateways, links) are automatically cleaned up as part of their parent stacks.

For all options, run `./destroy.sh --help`.

Alternatively, you can delete stacks manually:

1. Navigate to the AWS CloudFormation console.
2. Delete the `prebid-server-deployment-on-aws` stack first.
3. Delete the `BiddingServerSimulator` stack (if deployed).
4. Note that some resources like S3 buckets with content may require manual deletion.

## FAQ, Known Issues, Additional Considerations, and Limitations

### Known Issues
 - When deploying RTB fabric components for the first time you may hit an error related to Service Linked IAM role. This could be a timing issue as the first api call is setting up IAM role in the background. Validate in IAM console that the AWS RTB Fabric Service linked role exist and Re-run the deployment again
 - The demo website uses pre-built jar files hosted on 3rd party CDN. As versions of these dependencies roll, these may need to be re-pointed

### Additional considerations

- All S3 buckets created by this solution have public access blocked and use encryption at rest.
- CloudFront deployment mode uses custom header authentication. ALB-only mode requires user-provided SSL certificates for HTTPS.
- Customers are responsible for reviewing and validating all IAM roles, policies, and security group configurations created by this solution to ensure they meet their organization's security requirements and compliance standards.
- For any feedback, questions, or suggestions, please use the issues tab under the [GitHub repository](https://github.com/aws-solutions-library-samples/prebid-server-deployment-on-aws).

## Revisions
See [CHANGELOG.md](./CHANGELOG.md) for revisions.

## Notices

Customers are responsible for making their own independent assessment of the information in this Guidance. This Guidance: (a) is for informational purposes only, (b) represents AWS current product offerings and practices, which are subject to change without notice, and (c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. AWS responsibilities and liabilities to its customers are controlled by AWS agreements, and this Guidance is not part of, nor does it modify, any agreement between AWS and its customers.

## Collection of operational metrics

This solution collects anonymized operational metrics to help AWS improve the quality of features of the solution.
For more information, including how to disable this capability, please see the [implementation guide](https://docs.aws.amazon.com/solutions/latest/prebid-server-deployment-on-aws/anonymized-data-collection.html).

## Authors

For a list of contributors, please see [Contributors](https://docs.aws.amazon.com/solutions/latest/prebid-server-deployment-on-aws/contributors.html).

***

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.