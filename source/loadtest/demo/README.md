# Demo

This document provides instructions for setting up and running a demo for Prebid Server on AWS using prebid.js, a simulated bidding server and the AMT bid adapter. The demo helps evaluate the end-2-end functionality of the Prebid Server with mocked data.

## Prerequisites

1. Deployed Prebid Server on AWS including the bidder simulator [see /README.md](/README.md)

2. Retrieve Prebid Server endpoint hostname from the Prebid Server CF stack output named `PrebidCloudFrontDistributionEndpoint` and the demo page base URL from the bidder simulator CF stack output named `DemoWebsiteUrl`. 

## Run the demo

1. In your web browser enter the following URL replacing the `<placeholders>` with above retrieved values. 
```
<DemoWebsiteUrl>?prebidserver=<PrebidCloudFrontDistributionEndpoint>
```

2. Open the browser console to follow network requests for debugging.

The demo page loads [./app.js](./app.js) which will automatically retrieve the Prebid Server endpoint hostname from query parameter `?prebidserver=`, starts `prebid.js` and executes a single request to Prebid Server  `/auction` with the following ad units:
  
  * **banner_imp_1**: 300x250 banner ad unit
  * **banner_imp_2**: 300x250 banner ad unit
  * **outstream_video_imp_1**: 360x360 outstream video ad unit
  * **instream_video_imp_1**: 640x480 instream video ad unit (preroll in videojs player)

You should see all 4 ad units rendering immediately after the page loaded.
