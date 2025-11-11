package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Value;

@Builder
@Value
public class PsdoaBid {

    @JsonProperty("bid")
    String bid;

    @JsonProperty("bidder")
    String bidder;

    @JsonProperty("price")
    Double price;

    @JsonProperty("currency")
    String currency;

    @JsonProperty("creative_id")
    String creativeId;

    @JsonProperty("width")
    Integer width;

    @JsonProperty("height")
    Integer height;

    @JsonProperty("deal_id")
    String dealId;

    @JsonProperty("creative_type")
    String creativeType;
}
