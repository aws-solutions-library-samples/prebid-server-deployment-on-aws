### AMT Bidder Directory

This directory `amt-bidder` is intentionally maintained as empty in version control.

- **For deployments without bidder simulator**: Leave empty which empty directory ensures Docker COPY commands succeed regardless of deployment type.
- **For deployments with bidder simulator**: When using `./deploy.sh --deploy-bidding-simulator` the script will populate this directory with the necessary prebid adapter source code files from source/loadtest/amt-bidder
 