# Load Test

This document covers testing and load testing a Prebid Server on AWS deployment using the bidder simulator and the AMT bid adapter.

## Test Auction Requests

After deployment, use the provided test script to validate the setup. The script sends full OpenRTB 2.x requests to the `/openrtb2/auction` endpoint and validates the responses.

```bash
cd source/loadtest

# Test banner + outstream video
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type banner+outstream

# Test instream video (preroll + midroll)
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type instream

# Test all request types
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type all

# Verbose output with full request/response payloads
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type all --verbose

# Use a custom request file
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type banner+outstream --request-file custom.json

# Dump request JSON without sending (useful for inspection)
python test-auction-amt.py --endpoint <your-cloudfront-dns-name> --type all --dump
```

### Request Types

| Type | Impressions | Description |
|------|-------------|-------------|
| `banner+outstream` | `banner_imp_1` (300x250), `banner_imp_2` (728x90), `outstream_video_imp_1` (640x480) | Banner display ads + outstream in-article video |
| `instream` | `instream_video_imp_1` (preroll), `instream_video_imp_2` (midroll) | Instream video with preroll (startdelay=0) and midroll (startdelay=900) |

### Example Output

```
OpenRTB 2.x Prebid Server Test
Endpoint: https://d1234567890.cloudfront.net

============================================================
  BANNER + OUTSTREAM  →  /openrtb2/auction
============================================================
✓ Loaded request from: openrtb2-banner-outstream-request.json
Impressions: banner_imp_1, banner_imp_2, outstream_video_imp_1

=== RESPONSE (200) ===
✓ id present
✓ seatbid present
✓ cur present
✓ 1 seat(s) returned
  seat=amt  bids=3
    impid=banner_imp_1  price=3.25  crid=banner_creative_1  type=banner
    impid=banner_imp_2  price=2.75  crid=banner_creative_2  type=banner
    impid=outstream_video_imp_1  price=12.5  crid=outstream_video_creative_1  type=video

=== SUMMARY ===
  ✓ banner+outstream
  ✓ instream
```

### Request JSON Files

Default request payloads are provided as JSON files in `source/loadtest/`:
- `openrtb2-banner-outstream-request.json` — Banner + outstream video request
- `openrtb2-instream-video-request.json` — Instream preroll + midroll video request

These can be customized directly or overridden with `--request-file`.

### Test Script Options

```bash
python test-auction-amt.py --help
```

## Bidder Simulator Configuration

The bidder simulator uses Application Load Balancer (ALB), and Lambda to respond to bid requests from Prebid Server. This architecture enables both direct internet access and RTB Fabric integration.

### Deploying the Bidder Simulator

The bidder simulator is the `BiddingServerSimulator` CDK stack (defined in
`source/infrastructure/lib/bidder_simulator/bidder-simulator-stack.ts`). Deploy it
together with Prebid Server using the `deploy.sh` script:

```bash
# from the repo root
./deploy.sh --deploy-bidding-simulator --profile <your-profile> --region <your-region>
```

### Bid Response Format

The bid response follows the [OpenRTB specification](https://www.iab.com/wp-content/uploads/2016/03/OpenRTB-API-Specification-Version-2-5-FINAL.pdf#page=32):

```json
{
  "id": "request_id",
  "seatbid": [
    {
      "bid": [
        {
          "id": "bid_id_1",
          "impid": "imp_id_1",
          "price": 3.33,
          "crid": "creativeId"
        },
        {
          "id": "bid_id_2",
          "impid": "imp_id_1",
          "price": 5.55,
          "crid": "creativeId"
        }
      ]
    }
  ]
}
```

### Simulate Bid Response Delays

Configure bid response delays using CloudFormation parameters:
- `BID_RESPONSES_DELAY_PERCENTAGE`: Portion of requests that will experience delays (0.0 to 1.0)
- `A_BID_RESPONSE_DELAY_PROBABILITY`: Likelihood of an individual bid response being delayed (0.0 to 1.0)

By default, delayed bid response simulation is disabled.

### Simulate Bid Response Timeouts

Configure bid response timeouts using CloudFormation parameters:
- `BID_RESPONSES_TIMEOUT_PERCENTAGE`: Portion of requests that will experience timeouts (0.0 to 1.0)
- `A_BID_RESPONSE_TIMEOUT_PROBABILITY`: Likelihood of an individual bid response timing out (0.0 to 1.0)

By default, timeout simulation is disabled.

## Load Testing with JMeter

### Update or Create Test Plan

1. Download and install [Apache JMeter](https://jmeter.apache.org/download_jmeter.cgi)
2. Open the example test plan: `source/loadtest/jmx/prebid_server_test_plan_using_amt_adapter.jmx`
3. Update the `url` in User Defined Variables with your CloudFront endpoint
4. Optional: Update HTTP Request settings under Thread Group
5. Start the tests to verify proper operation

### Distributed Load Testing (DLT)

Use the [Distributed Load Testing on AWS](https://aws.amazon.com/solutions/implementations/distributed-load-testing-on-aws/) solution to automate load tests:

1. Follow the DLT implementation guide to set up the solution
2. Upload your JMeter test plan to start load tests

#### Deploying DLT in the Prebid Server VPC

When deploying DLT into the same VPC as Prebid Server (recommended for simplicity), the DLT Fargate tasks use the VPC's S3 Gateway endpoint. This endpoint has a restrictive policy that only allows access to specific buckets. You must add the DLT storage bucket to the policy.

**Setup steps:**

1. **Deploy DLT with the Prebid Server VPC and private subnets:**

   During DLT stack creation, configure:
   - **Existing VPC ID**: Use the Prebid Server VPC ID (from `aws ec2 describe-vpcs` or CloudFormation outputs)
   - **First existing subnet**: Prebid Server private subnet 1 (has NAT gateway for outbound internet)
   - **Second existing subnet**: Prebid Server private subnet 2
   - Leave the CIDR block fields unchanged (they are ignored when using an existing VPC)

2. **Update the S3 VPC Gateway endpoint policy:**

   The Prebid Server VPC's S3 Gateway endpoint restricts bucket access. Add the DLT storage bucket with `GetObject`, `PutObject`, and `ListBucket` permissions:

   ```bash
   # Find the DLT storage bucket name
   aws cloudformation describe-stacks \
     --stack-name <DLT-stack-name> \
     --query "Stacks[0].Outputs[?OutputKey=='ScenariosBucket'].OutputValue" \
     --output text

   # Find the S3 VPC endpoint ID
   aws ec2 describe-vpc-endpoints \
     --filters "Name=vpc-id,Values=<prebid-vpc-id>" "Name=service-name,Values=com.amazonaws.<region>.s3" \
     --query 'VpcEndpoints[0].VpcEndpointId' \
     --output text

   # Update the endpoint policy to include the DLT bucket
   # Add this statement to the existing policy:
   #   {
   #     "Effect": "Allow",
   #     "Principal": {"AWS": "*"},
   #     "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
   #     "Resource": [
   #       "arn:aws:s3:::<dlt-bucket-name>",
   #       "arn:aws:s3:::<dlt-bucket-name>/*"
   #     ],
   #     "Condition": {"StringEquals": {"aws:ResourceAccount": "<account-id>"}}
   #   }
   ```

   The DLT tasks need:
   - `GetObject` — to download the JMX test plan from S3
   - `PutObject` — to upload test results back to S3
   - `ListBucket` — for result file enumeration

   Without `PutObject`, tests will run successfully but results will fail to parse with: `"Failed to parse the results - Cannot read properties of undefined (reading 'Key')"`

3. **Configure the JMeter test plan:**

   Update the `url` variable in your JMX file to the Prebid Server CloudFront domain name (e.g., `d1234567890.cloudfront.net`). The DLT tasks reach Prebid Server via the public CloudFront endpoint — no VPC peering or internal routing needed.
