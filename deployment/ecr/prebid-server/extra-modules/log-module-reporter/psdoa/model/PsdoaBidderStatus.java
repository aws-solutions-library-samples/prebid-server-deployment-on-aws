package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Value;

@Builder
@Value
public class PsdoaBidderStatus {

    @JsonProperty("bidder")
    String bidder;

    @JsonProperty("noCookie")
    Boolean noCookie;

    @JsonProperty("usersync")
    PsdoaUserSync usersync;

    @JsonProperty("error")
    String error;

    @JsonProperty("response_time_ms")
    Long responseTimeMs;
}
