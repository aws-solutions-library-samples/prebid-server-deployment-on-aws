#!/bin/bash

set -e

source_files=(
  "./amt-bidder/amt.json"
  "./amt-bidder/amt.yaml"
  "./amt-bidder/AmtBidder.java"
  "./amt-bidder/AmtBidderTest.java"
  "./amt-bidder/AmtConfiguration.java"
  "./amt-bidder/AmtTest.java"
  "./amt-bidder/ExtImpAmt.java"
  "./amt-bidder/test-amt-bid-request.json"
  "./amt-bidder/test-amt-bid-response.json"
  "./amt-bidder/test-auction-amt-request.json"
  "./amt-bidder/test-auction-amt-response.json"
)

destinations=(
  "./src/main/resources/static/bidder-params/"
  "./src/main/resources/bidder-config/"
  "./src/main/java/org/prebid/server/bidder/amt/"
  "./src/test/java/org/prebid/server/bidder/amt/"
  "./src/main/java/org/prebid/server/spring/config/bidder/"
  "./src/test/java/org/prebid/server/it/"
  "./src/main/java/org/prebid/server/proto/openrtb/ext/request/amt/"
  "./src/test/resources/org/prebid/server/it/openrtb2/amt/"
  "./src/test/resources/org/prebid/server/it/openrtb2/amt/"
  "./src/test/resources/org/prebid/server/it/openrtb2/amt/"
  "./src/test/resources/org/prebid/server/it/openrtb2/amt/"
)


# Check if arrays have the same length
if [ ${#source_files[@]} -ne ${#destinations[@]} ]; then
  echo "Error: Number of source files and destinations do not match"
  exit 1
fi

# Loop through the arrays and copy files
for i in "${!source_files[@]}"; do
  source_file="${source_files[$i]}"
  destination="${destinations[$i]}"
  
  mkdir -p "$destination" # Create the destination directory if it doesn't exist
  cp -v "$source_file" "$destination"
done

# update test-application.properties file
echo "adapters.amt.enabled=true
adapters.amt.endpoint=http://localhost:8090/amt-exchange
" >> ./src/test/resources/org/prebid/server/it/test-application.properties
