package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Value;

@Builder
@Value
public class PsdoaUserSync {

    @JsonProperty("url")
    String url;

    @JsonProperty("type")
    String type;

    @JsonProperty("status")
    String status;
}
